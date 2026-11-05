#include <windows.h>
#include <sddl.h>
#include <node_api.h>
#include <uv.h>
#include <winternl.h>
#include <cstring>
#include <algorithm>
#include <array>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "content-preparation.h"

namespace {
void need(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
struct Handle {
  HANDLE value=nullptr;
  Handle()=default;explicit Handle(HANDLE h):value(h){}
  Handle(const Handle&)=delete;Handle& operator=(const Handle&)=delete;
  ~Handle(){close();}
  void close(){if(value&&value!=INVALID_HANDLE_VALUE)CloseHandle(value);value=nullptr;}
};
struct Local {void* value=nullptr;~Local(){if(value)LocalFree(value);}};
std::wstring sidText(PSID sid){Local text;need(ConvertSidToStringSidW(sid,reinterpret_cast<LPWSTR*>(&text.value))!=0,"peer_token_sid");return static_cast<wchar_t*>(text.value);}
struct Identity {
  std::wstring sid;LUID authentication{};DWORD session=0;bool appContainer=false;
  bool operator==(const Identity& other)const{return sid==other.sid&&authentication.HighPart==other.authentication.HighPart&&authentication.LowPart==other.authentication.LowPart&&session==other.session&&appContainer==other.appContainer;}
};
Identity identity(HANDLE process){
  Handle token;need(OpenProcessToken(process,TOKEN_QUERY,&token.value)!=0,"peer_token");DWORD size=0;
  GetTokenInformation(token.value,TokenUser,nullptr,0,&size);need(size>0&&size<65536,"peer_token");std::vector<unsigned char> bytes(size);
  need(GetTokenInformation(token.value,TokenUser,bytes.data(),size,&size)!=0,"peer_token");Identity result;result.sid=sidText(reinterpret_cast<TOKEN_USER*>(bytes.data())->User.Sid);
  TOKEN_STATISTICS statistics{};need(GetTokenInformation(token.value,TokenStatistics,&statistics,sizeof(statistics),&size)!=0&&statistics.TokenType==TokenPrimary,"peer_token");result.authentication=statistics.AuthenticationId;
  need(GetTokenInformation(token.value,TokenSessionId,&result.session,sizeof(result.session),&size)!=0,"peer_token");DWORD container=0;
  need(GetTokenInformation(token.value,TokenIsAppContainer,&container,sizeof(container),&size)!=0,"peer_token");result.appContainer=container!=0;return result;
}
unsigned long long created(HANDLE process){FILETIME birth{},exit{},kernel{},user{};need(GetProcessTimes(process,&birth,&exit,&kernel,&user)!=0,"peer_process_time");return (static_cast<unsigned long long>(birth.dwHighDateTime)<<32)|birth.dwLowDateTime;}
struct Peer {
  Handle process;DWORD pid;unsigned long long creation;Identity token;
  explicit Peer(DWORD id):process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION|PROCESS_DUP_HANDLE|SYNCHRONIZE,FALSE,id)),pid(id){
    need(process.value!=nullptr,"peer_process_open");creation=created(process.value);token=identity(process.value);need(!token.appContainer,"peer_app_container");check();
  }
  void check(){need(WaitForSingleObject(process.value,0)==WAIT_TIMEOUT&&GetProcessId(process.value)==pid&&created(process.value)==creation,"peer_process_gone");need(identity(process.value)==token,"peer_identity_changed");}
};
struct Io {
  Handle event;OVERLAPPED value{};bool pending=false,inlineConnect=false;
  Io():event(CreateEventW(nullptr,TRUE,FALSE,nullptr)){need(event.value!=nullptr,"peer_event");value.hEvent=event.value;}
  void prepare(){need(!pending,"peer_io_busy");need(ResetEvent(event.value)!=0,"peer_event");value={};value.hEvent=event.value;inlineConnect=false;}
  void submitted(BOOL ok,DWORD error){need(ok||error==ERROR_IO_PENDING,"peer_io");pending=true;if(ok)need(SetEvent(event.value)!=0,"peer_event");}
  bool complete(HANDLE pipe,DWORD& count){
    if(!pending||WaitForSingleObject(event.value,0)==WAIT_TIMEOUT)return false;
    if(inlineConnect)count=0;else need(GetOverlappedResult(pipe,&value,&count,FALSE)!=0,"peer_connection_closed");
    pending=false;inlineConnect=false;return true;
  }
  void cancel(HANDLE pipe){if(pending&&!inlineConnect){CancelIoEx(pipe,&value);DWORD ignored=0;GetOverlappedResult(pipe,&value,&ignored,TRUE);}pending=false;inlineConnect=false;}
};
struct Pipe {
  Handle handle;Io readIo,writeIo;std::shared_ptr<Peer> peer;
  bool server=false,connected=false,closed=false;std::array<unsigned char,65540> buffer{};std::vector<unsigned char> input,output;
  Pipe(const std::wstring& name,std::shared_ptr<Peer> expected,bool listen):peer(std::move(expected)),server(listen){
    peer->check();const std::wstring prefix=L"\\\\.\\pipe\\LeafSeamer.Install.";need(name.rfind(prefix,0)==0&&name.size()>prefix.size()&&name.size()<=128,"peer_endpoint_name");
    for(size_t i=prefix.size();i<name.size();++i)need((name[i]>=L'a'&&name[i]<=L'z')||(name[i]>=L'0'&&name[i]<=L'9')||name[i]==L'-',"peer_endpoint_name");
    if(server){
      const auto own=identity(GetCurrentProcess());const auto sddl=L"D:P(A;;FA;;;SY)(A;;FA;;;"+own.sid+L")(A;;0x00120083;;;"+peer->token.sid+L")";
      Local descriptor;need(ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(),SDDL_REVISION_1,&descriptor.value,nullptr)!=0,"peer_endpoint_acl");
      SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES),descriptor.value,FALSE};
      handle.value=CreateNamedPipeW(name.c_str(),PIPE_ACCESS_DUPLEX|FILE_FLAG_OVERLAPPED|FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE|PIPE_READMODE_BYTE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,1,65540,65540,0,&security);
      need(handle.value!=INVALID_HANDLE_VALUE,"peer_endpoint_unavailable");readIo.prepare();
      const BOOL ok=ConnectNamedPipe(handle.value,&readIo.value);const DWORD error=GetLastError();
      if(!ok&&error==ERROR_PIPE_CONNECTED){readIo.pending=true;readIo.inlineConnect=true;need(SetEvent(readIo.event.value)!=0,"peer_event");}else readIo.submitted(ok,error);
    }else{
      handle.value=CreateFileW(name.c_str(),FILE_READ_DATA|FILE_WRITE_DATA|FILE_READ_ATTRIBUTES|READ_CONTROL|SYNCHRONIZE,0,nullptr,OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED|SECURITY_SQOS_PRESENT|SECURITY_IDENTIFICATION,nullptr);
      need(handle.value!=INVALID_HANDLE_VALUE,"peer_endpoint_unavailable");connected=true;verify();read();
    }
  }
  ~Pipe(){close();}
  void close(){if(closed)return;closed=true;if(handle.value&&handle.value!=INVALID_HANDLE_VALUE){readIo.cancel(handle.value);writeIo.cancel(handle.value);if(server)DisconnectNamedPipe(handle.value);}handle.close();input.clear();output.clear();peer.reset();}
  void verify(){need(!closed,"peer_closed");peer->check();if(connected){ULONG actual=0;need((server?GetNamedPipeClientProcessId(handle.value,&actual):GetNamedPipeServerProcessId(handle.value,&actual))&&actual==peer->pid,"peer_process_mismatch");}}
  void read(){readIo.prepare();DWORD count=0;const DWORD available=static_cast<DWORD>(buffer.size()-input.size());need(available>0,"peer_frame_capacity");
    const BOOL ok=ReadFile(handle.value,buffer.data(),available,&count,&readIo.value);readIo.submitted(ok,GetLastError());}
  std::vector<unsigned char> poll(){
    verify();DWORD count=0;
    if(!connected){if(!readIo.complete(handle.value,count))return {};connected=true;verify();read();return {};}
    if(writeIo.complete(handle.value,count)){need(count==output.size(),"peer_partial_write");output.clear();}
    if(readIo.complete(handle.value,count)){need(count>0&&input.size()+count<=buffer.size(),"peer_frame_capacity");input.insert(input.end(),buffer.begin(),buffer.begin()+count);}
    std::vector<unsigned char> packet;
    if(input.size()>=4){const size_t length=static_cast<size_t>(input[0])|(static_cast<size_t>(input[1])<<8)|(static_cast<size_t>(input[2])<<16)|(static_cast<size_t>(input[3])<<24);
      need(length>0&&length<=65536,"peer_frame_capacity");if(input.size()>=length+4){packet.assign(input.begin()+4,input.begin()+4+length);input.erase(input.begin(),input.begin()+4+length);}}
    if(!readIo.pending)read();verify();return packet;
  }
  void send(const unsigned char* data,size_t length){verify();need(connected&&!writeIo.pending&&output.empty(),"peer_write_busy");need(length>0&&length<=65536,"peer_frame_capacity");
    output.resize(length+4);for(size_t i=0;i<4;++i)output[i]=static_cast<unsigned char>((length>>(8*i))&255);std::copy(data,data+length,output.begin()+4);
    writeIo.prepare();DWORD count=0;const BOOL ok=WriteFile(handle.value,output.data(),static_cast<DWORD>(output.size()),&count,&writeIo.value);writeIo.submitted(ok,GetLastError());
  }
};

constexpr napi_type_tag peerTag{0x9581936011ba4997ULL,0x953d8ded0500bef0ULL},pipeTag{0xbb173ea17ebf4fafULL,0xb85f4d01137c63bbULL};
void ok(napi_status status){need(status==napi_ok,"peer_argument");}
napi_value nothing(napi_env env){napi_value v;ok(napi_get_undefined(env,&v));return v;}
napi_value text(napi_env env,const std::wstring& str){napi_value v;ok(napi_create_string_utf16(env,reinterpret_cast<const char16_t*>(str.data()),str.size(),&v));return v;}
napi_value number(napi_env env,double n){napi_value v;ok(napi_create_double(env,n,&v));return v;}
void prop(napi_env env,napi_value object,const char* name,napi_value value){ok(napi_set_named_property(env,object,name,value));}
std::vector<napi_value> args(napi_env env,napi_callback_info info,size_t expected){size_t count=expected+1;std::vector<napi_value> values(count);ok(napi_get_cb_info(env,info,&count,values.data(),nullptr,nullptr));need(count==expected,"peer_argument");return values;}
std::wstring string(napi_env env,napi_value value,size_t max=128){size_t length=0;ok(napi_get_value_string_utf16(env,value,nullptr,0,&length));need(length>0&&length<=max,"peer_argument");std::vector<char16_t> bytes(length+1);size_t written=0;ok(napi_get_value_string_utf16(env,value,bytes.data(),bytes.size(),&written));need(written==length&&std::find(bytes.begin(),bytes.begin()+length,u'\0')==bytes.begin()+length,"peer_argument");return std::wstring(bytes.begin(),bytes.begin()+length);}
template<typename T> T* unwrap(napi_env env,napi_value value,const napi_type_tag& tag){bool valid=false;ok(napi_check_object_type_tag(env,value,&tag,&valid));need(valid,"peer_handle");void* raw=nullptr;ok(napi_unwrap(env,value,&raw));need(raw!=nullptr,"peer_handle");return static_cast<T*>(raw);}
template<typename T> void finalize(napi_env,void* value,void*){delete static_cast<T*>(value);}
template<typename T> napi_value wrap(napi_env env,std::unique_ptr<T> value,const napi_type_tag& tag){napi_value object;ok(napi_create_object(env,&object));ok(napi_type_tag_object(env,object,&tag));ok(napi_wrap(env,object,value.get(),finalize<T>,nullptr,nullptr));value.release();ok(napi_object_freeze(env,object));return object;}
napi_value fail(napi_env env,const std::exception& error){bool pending=false;napi_is_exception_pending(env,&pending);if(!pending)napi_throw_error(env,error.what(),error.what());return nullptr;}
using PeerBox=std::shared_ptr<Peer>;
void regularReadOnly(HANDLE handle){
  need(handle&&handle!=INVALID_HANDLE_VALUE&&GetFileType(handle)==FILE_TYPE_DISK,"peer_source_file");
  FILE_STANDARD_INFO standard{};FILE_ATTRIBUTE_TAG_INFO attributes{};
  need(GetFileInformationByHandleEx(handle,FileStandardInfo,&standard,sizeof(standard))&&
    GetFileInformationByHandleEx(handle,FileAttributeTagInfo,&attributes,sizeof(attributes))&&!standard.Directory&&
    !(attributes.FileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT))&&standard.EndOfFile.QuadPart>=0&&
    standard.EndOfFile.QuadPart<=536870912,"peer_source_file");
  using Query=NTSTATUS(NTAPI*)(HANDLE,OBJECT_INFORMATION_CLASS,PVOID,ULONG,PULONG);
  const auto address=GetProcAddress(GetModuleHandleW(L"ntdll.dll"),"NtQueryObject");need(address!=nullptr,"peer_source_access_unavailable");
  Query query;static_assert(sizeof(query)==sizeof(address));std::memcpy(&query,&address,sizeof(query));
  PUBLIC_OBJECT_BASIC_INFORMATION basic{};ULONG length=0;need(query(handle,ObjectBasicInformation,&basic,sizeof(basic),&length)>=0,"peer_source_access_unavailable");
  constexpr ACCESS_MASK writable=FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|DELETE|WRITE_DAC|WRITE_OWNER;
  need((basic.GrantedAccess&FILE_READ_DATA)&&!(basic.GrantedAccess&writable),"peer_source_read_only");
}
napi_value sourceHandle(napi_env env,napi_callback_info info){try{
  double fd=0;ok(napi_get_value_double(env,args(env,info,1)[0],&fd));need(std::isfinite(fd)&&fd>=0&&fd<=2147483647&&std::floor(fd)==fd,"peer_argument");
  const auto handle=uv_get_osfhandle(static_cast<int>(fd));regularReadOnly(handle);return text(env,std::to_wstring(reinterpret_cast<uintptr_t>(handle)));
}catch(const std::exception& e){return fail(env,e);}}
napi_value duplicateSource(napi_env env,napi_callback_info info){try{
  const auto a=args(env,info,2);auto p=unwrap<Pipe>(env,a[0],pipeTag);need(p->server&&p->connected,"peer_server_required");p->verify();
  const auto value=string(env,a[1]);need(value.size()<=20&&value[0]!=L'0'&&std::all_of(value.begin(),value.end(),[](wchar_t c){return c>=L'0'&&c<=L'9';}),"peer_source_handle");
  const auto raw=std::stoull(value);need(raw>0&&raw<=UINTPTR_MAX-16,"peer_source_handle");Handle source;
  need(DuplicateHandle(p->peer->process.value,reinterpret_cast<HANDLE>(static_cast<uintptr_t>(raw)),GetCurrentProcess(),&source.value,0,FALSE,DUPLICATE_SAME_ACCESS)!=0,"peer_source_handle");
  regularReadOnly(source.value);p->verify();
  const int fd=uv_open_osfhandle(source.value);need(fd>=0,"peer_source_descriptor");source.value=nullptr;
  try{return number(env,fd);}catch(...){uv_fs_t request{};uv_fs_close(nullptr,&request,fd,nullptr);uv_fs_req_cleanup(&request);throw;}
}catch(const std::exception& e){return fail(env,e);}}
napi_value capture(napi_env env,napi_callback_info info){try{const auto a=args(env,info,1);double pid=0;ok(napi_get_value_double(env,a[0],&pid));need(std::isfinite(pid)&&pid>=1&&pid<=4294967295.0&&std::floor(pid)==pid,"peer_argument");return wrap(env,std::make_unique<PeerBox>(std::make_shared<Peer>(static_cast<DWORD>(pid))),peerTag);}catch(const std::exception& e){return fail(env,e);}}
napi_value describe(napi_env env,napi_callback_info info){try{auto p=*unwrap<PeerBox>(env,args(env,info,1)[0],peerTag);p->check();napi_value result;ok(napi_create_object(env,&result));prop(env,result,"pid",number(env,p->pid));prop(env,result,"creation_time",text(env,std::to_wstring(p->creation)));prop(env,result,"user_sid",text(env,p->token.sid));prop(env,result,"session_id",number(env,p->token.session));prop(env,result,"authentication_id",text(env,std::to_wstring(static_cast<unsigned long>(p->token.authentication.HighPart))+L":"+std::to_wstring(p->token.authentication.LowPart)));ok(napi_object_freeze(env,result));return result;}catch(const std::exception& e){return fail(env,e);}}
napi_value endpoint(napi_env env,napi_callback_info info){try{const auto a=args(env,info,3);bool server=false;ok(napi_get_value_bool(env,a[2],&server));return wrap(env,std::make_unique<Pipe>(string(env,a[0]),*unwrap<PeerBox>(env,a[1],peerTag),server),pipeTag);}catch(const std::exception& e){return fail(env,e);}}
napi_value poll(napi_env env,napi_callback_info info){Pipe* p=nullptr;try{p=unwrap<Pipe>(env,args(env,info,1)[0],pipeTag);auto packet=p->poll();napi_value result,connected,writable,body;ok(napi_create_object(env,&result));ok(napi_get_boolean(env,p->connected,&connected));ok(napi_get_boolean(env,p->connected&&!p->writeIo.pending&&p->output.empty(),&writable));ok(napi_create_buffer_copy(env,packet.size(),packet.data(),nullptr,&body));prop(env,result,"connected",connected);prop(env,result,"writable",writable);prop(env,result,"packet",body);return result;}catch(const std::exception& e){if(p)p->close();return fail(env,e);}}
napi_value send(napi_env env,napi_callback_info info){Pipe* p=nullptr;try{const auto a=args(env,info,2);p=unwrap<Pipe>(env,a[0],pipeTag);void* bytes=nullptr;size_t length=0;bool buffer=false;ok(napi_is_buffer(env,a[1],&buffer));need(buffer,"peer_argument");ok(napi_get_buffer_info(env,a[1],&bytes,&length));p->send(static_cast<unsigned char*>(bytes),length);return nothing(env);}catch(const std::exception& e){if(p)p->close();return fail(env,e);}}
napi_value close(napi_env env,napi_callback_info info){try{unwrap<Pipe>(env,args(env,info,1)[0],pipeTag)->close();return nothing(env);}catch(const std::exception& e){return fail(env,e);}}
napi_value check(napi_env env,napi_callback_info info){Pipe* p=nullptr;try{p=unwrap<Pipe>(env,args(env,info,1)[0],pipeTag);need(p->connected,"peer_not_connected");p->verify();return nothing(env);}catch(const std::exception& e){if(p)p->close();return fail(env,e);}}
constexpr napi_type_tag contentTag{0x582f63ae37cf4c69ULL,0xa311229f13cf6288ULL},preparedTag{0x60a9effaceb644bcULL,0x92c8a5f0b8a7a212ULL};
napi_value property(napi_env env,napi_value value,const char* name){napi_value result;ok(napi_get_named_property(env,value,name,&result));return result;}
uint32_t count(napi_env env,napi_value value,uint32_t max){bool array=false;ok(napi_is_array(env,value,&array));need(array,"preparation_argument");uint32_t length=0;ok(napi_get_array_length(env,value,&length));need(length<=max,"preparation_capacity");return length;}
napi_value contentPin(napi_env env,napi_callback_info info){try{
  const auto a=args(env,info,2);const auto length=count(env,a[1],65536);std::vector<content::Entry> entries;
  for(uint32_t i=0;i<length;++i){napi_value item;ok(napi_get_element(env,a[1],i,&item));const auto rawSize=string(env,property(env,item,"size_bytes"),20),rawDigest=string(env,property(env,item,"digest"),71);
    need(rawSize.find_first_not_of(L"0123456789")==std::wstring::npos&&(rawSize.size()==1||rawSize[0]!=L'0'),"preparation_size");const auto size=std::stoull(rawSize);need(size<=268435456,"preparation_capacity");
    std::string digest;for(const auto c:rawDigest){need(c<=127,"preparation_digest");digest+=static_cast<char>(c);}
    entries.push_back({string(env,property(env,item,"path"),240),size,digest});}
  return wrap(env,std::make_unique<content::Pin>(string(env,a[0],32760),entries,5000),contentTag);
}catch(const std::exception& e){return fail(env,e);}}
napi_value contentVerify(napi_env env,napi_callback_info info){try{unwrap<content::Pin>(env,args(env,info,1)[0],contentTag)->check(5000);return nothing(env);}catch(const std::exception& e){return fail(env,e);}}
napi_value contentRead(napi_env env,napi_callback_info info){try{const auto a=args(env,info,3);double maximum=0;ok(napi_get_value_double(env,a[2],&maximum));
  need(std::isfinite(maximum)&&maximum>=1&&maximum<=1048576&&std::floor(maximum)==maximum,"content_read_capacity");
  const auto bytes=unwrap<content::Pin>(env,a[0],contentTag)->read(string(env,a[1]),static_cast<unsigned long>(maximum));napi_value result;
  ok(napi_create_buffer_copy(env,bytes.size(),bytes.data(),nullptr,&result));return result;
}catch(const std::exception& e){return fail(env,e);}}
napi_value contentClose(napi_env env,napi_callback_info info){try{unwrap<content::Pin>(env,args(env,info,1)[0],contentTag)->close();return nothing(env);}catch(const std::exception& e){return fail(env,e);}}
napi_value prepareRoot(napi_env env,napi_callback_info info){try{
  const auto a=args(env,info,3);std::vector<std::wstring> readers;const auto length=count(env,a[2],16);
  for(uint32_t i=0;i<length;++i){napi_value item;ok(napi_get_element(env,a[2],i,&item));readers.push_back(string(env,item,184));}
  return wrap(env,std::make_unique<prepared::Root>(string(env,a[0],32760),string(env,a[1],36),readers),preparedTag);
}catch(const std::exception& e){return fail(env,e);}}
napi_value protectObject(napi_env env,napi_callback_info info){try{
  const auto a=args(env,info,4);bool directory=false,apply=false;ok(napi_get_value_bool(env,a[2],&directory));ok(napi_get_value_bool(env,a[3],&apply));
  unwrap<prepared::Root>(env,a[0],preparedTag)->check(string(env,a[1],240),directory,apply);return nothing(env);
}catch(const std::exception& e){return fail(env,e);}}
napi_value reopenPreparedRoot(napi_env env,napi_callback_info info){try{
  const auto a=args(env,info,4);std::vector<std::wstring> readers;const auto length=count(env,a[2],16);
  for(uint32_t i=0;i<length;++i){napi_value item;ok(napi_get_element(env,a[2],i,&item));readers.push_back(string(env,item,184));}
  const auto expected=string(env,a[3],48);need(expected.size()==48,"preparation_identity");
  return wrap(env,std::make_unique<prepared::Root>(string(env,a[0],32760),string(env,a[1],36),readers,expected),preparedTag);
}catch(const std::exception& e){return fail(env,e);}}
napi_value preparedDescribe(napi_env env,napi_callback_info info){try{
  const auto p=unwrap<prepared::Root>(env,args(env,info,1)[0],preparedTag);napi_value result;ok(napi_create_object(env,&result));
  prop(env,result,"root_identity",text(env,p->identity));prop(env,result,"writer_sid",text(env,p->writer));prop(env,result,"path",text(env,p->path));
  prop(env,result,"parent_identity",text(env,p->parentIdentity()));
  const auto observed=p->storageIdentity();napi_value storage;ok(napi_create_object(env,&storage));
  prop(env,storage,"format",text(env,L"windows-content-volume/1"));prop(env,storage,"volume_guid_path",text(env,observed.volume));
  prop(env,storage,"filesystem",text(env,observed.filesystem));prop(env,storage,"filesystem_serial",text(env,observed.serial));
  prop(env,storage,"file_id_volume_serial",text(env,p->identity.substr(0,16)));prop(env,storage,"filesystem_flags",text(env,observed.flags));
  prop(env,storage,"maximum_component_length",text(env,observed.maximumComponent));prop(env,storage,"sectors_per_allocation_unit",text(env,observed.sectorsPerCluster));
  prop(env,storage,"bytes_per_sector",text(env,observed.bytesPerSector));prop(env,result,"storage_identity",storage);return result;
}catch(const std::exception& e){return fail(env,e);}}
napi_value preparedClose(napi_env env,napi_callback_info info){try{unwrap<prepared::Root>(env,args(env,info,1)[0],preparedTag)->close();return nothing(env);}catch(const std::exception& e){return fail(env,e);}}
napi_value flushPreparedObject(napi_env env,napi_callback_info info){try{const auto a=args(env,info,3);bool directory=false;ok(napi_get_value_bool(env,a[2],&directory));unwrap<prepared::Root>(env,a[0],preparedTag)->flush(string(env,a[1],240),directory);return nothing(env);}catch(const std::exception& e){return fail(env,e);}}
napi_value flushPreparedParent(napi_env env,napi_callback_info info){try{return text(env,unwrap<prepared::Root>(env,args(env,info,1)[0],preparedTag)->flushParent());}catch(const std::exception& e){return fail(env,e);}}
napi_value initializeContentDirectory(napi_env env,napi_callback_info info){try{prepared::initializeDirectory(string(env,args(env,info,1)[0],32760));return nothing(env);}catch(const std::exception& e){return fail(env,e);}}
napi_value materializationTick(napi_env env,napi_callback_info){try{
  ULONGLONG tick=0;QueryInterruptTimePrecise(&tick);need(tick<=UINT64_MAX/100,"materialization_clock_overflow");
  return text(env,std::to_wstring(tick*100));
}catch(const std::exception& e){return fail(env,e);}}
napi_value init(napi_env env,napi_value exports){const napi_property_descriptor methods[]={
  {"materializationTick",nullptr,materializationTick,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"capture",nullptr,capture,nullptr,nullptr,nullptr,napi_default,nullptr},{"describe",nullptr,describe,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"endpoint",nullptr,endpoint,nullptr,nullptr,nullptr,napi_default,nullptr},{"poll",nullptr,poll,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"send",nullptr,send,nullptr,nullptr,nullptr,napi_default,nullptr},{"close",nullptr,close,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"check",nullptr,check,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"sourceHandle",nullptr,sourceHandle,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"duplicateSource",nullptr,duplicateSource,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"contentPin",nullptr,contentPin,nullptr,nullptr,nullptr,napi_default,nullptr},{"contentVerify",nullptr,contentVerify,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"contentClose",nullptr,contentClose,nullptr,nullptr,nullptr,napi_default,nullptr},{"contentRead",nullptr,contentRead,nullptr,nullptr,nullptr,napi_default,nullptr},{"prepareRoot",nullptr,prepareRoot,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"reopenPreparedRoot",nullptr,reopenPreparedRoot,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"protectObject",nullptr,protectObject,nullptr,nullptr,nullptr,napi_default,nullptr},{"preparedDescribe",nullptr,preparedDescribe,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"preparedClose",nullptr,preparedClose,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"flushPreparedObject",nullptr,flushPreparedObject,nullptr,nullptr,nullptr,napi_default,nullptr},{"flushPreparedParent",nullptr,flushPreparedParent,nullptr,nullptr,nullptr,napi_default,nullptr},
  {"initializeContentDirectory",nullptr,initializeContentDirectory,nullptr,nullptr,nullptr,napi_default,nullptr}};
  if(napi_define_properties(env,exports,sizeof(methods)/sizeof(methods[0]),methods)!=napi_ok)return nullptr;return exports;}
}
NAPI_MODULE(NODE_GYP_MODULE_NAME,init)
