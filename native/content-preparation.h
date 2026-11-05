#pragma once
#include "content-root.h"
#include <sddl.h>
#include <aclapi.h>
#include <cstring>

namespace prepared {
struct Local {void* value=nullptr;~Local(){if(value)LocalFree(value);}};
inline std::wstring sidText(PSID sid){Local text;content::need(sid&&ConvertSidToStringSidW(sid,reinterpret_cast<LPWSTR*>(&text.value)),"preparation_sid");return static_cast<wchar_t*>(text.value);}
inline std::wstring callerSid(){
  HANDLE raw=nullptr;content::need(OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&raw)!=0,"preparation_token");content::Handle token(raw);DWORD size=0;
  GetTokenInformation(token.value,TokenUser,nullptr,0,&size);content::need(size>0&&size<=65536,"preparation_token");std::vector<unsigned char> bytes(size);
  content::need(GetTokenInformation(token.value,TokenUser,bytes.data(),size,&size)!=0,"preparation_token");return sidText(reinterpret_cast<TOKEN_USER*>(bytes.data())->User.Sid);
}
inline bool trusted(const std::wstring& sid,const std::wstring& writer){return sid==writer||sid==L"S-1-5-18"||sid==L"S-1-5-32-544";}
inline void parentAccess(HANDLE handle,const std::wstring& writer){
  Local descriptor;PSID owner=nullptr;PACL acl=nullptr;
  content::need(GetSecurityInfo(handle,SE_FILE_OBJECT,OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,&owner,nullptr,&acl,nullptr,&descriptor.value)==ERROR_SUCCESS&&acl&&trusted(sidText(owner),writer),"preparation_parent_acl");
  constexpr ACCESS_MASK writes=GENERIC_WRITE|GENERIC_ALL|DELETE|WRITE_DAC|WRITE_OWNER|FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|FILE_DELETE_CHILD;
  for(DWORD index=0;index<acl->AceCount;++index){void* raw=nullptr;content::need(GetAce(acl,index,&raw)!=0,"preparation_parent_acl");auto header=static_cast<ACE_HEADER*>(raw);
    if(header->AceFlags&INHERIT_ONLY_ACE)continue;
    content::need(header->AceType==ACCESS_ALLOWED_ACE_TYPE||header->AceType==ACCESS_DENIED_ACE_TYPE,"preparation_parent_acl");
    if(header->AceType==ACCESS_ALLOWED_ACE_TYPE){auto ace=static_cast<ACCESS_ALLOWED_ACE*>(raw);content::need(!(ace->Mask&writes)||trusted(sidText(&ace->SidStart),writer),"preparation_parent_acl");}
  }
}
inline void initializeDirectory(std::wstring path){
  const auto writer=callerSid();if(path.rfind(L"\\\\?\\",0)==0)path.erase(0,4);
  content::need(path.size()>3&&path[1]==L':'&&path[2]==L'\\'&&GetDriveTypeW(path.substr(0,3).c_str())==DRIVE_FIXED,"preparation_local_root");
  std::vector<std::unique_ptr<content::Handle>> handles;std::wstring current=L"\\\\?\\"+path.substr(0,3);
  auto pin=[&](const std::wstring& name,DWORD access){auto handle=std::make_unique<content::Handle>(CreateFileW(name.c_str(),access,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    content::need(handle->value!=INVALID_HANDLE_VALUE,"preparation_directory");content::inspect(handle->value,true);handles.push_back(std::move(handle));};
  pin(current,FILE_READ_ATTRIBUTES);
  const auto segments=content::parts(path.substr(3),L'\\');
  for(size_t i=0;i<segments.size();++i){if(current.back()!=L'\\')current+=L'\\';current+=segments[i];pin(current,FILE_READ_ATTRIBUTES|(i+1==segments.size()?READ_CONTROL|WRITE_DAC|FILE_LIST_DIRECTORY:0));}
  const auto handle=handles.back()->value;Local previous;PSID owner=nullptr;
  content::need(GetSecurityInfo(handle,SE_FILE_OBJECT,OWNER_SECURITY_INFORMATION,&owner,nullptr,nullptr,nullptr,&previous.value)==ERROR_SUCCESS&&trusted(sidText(owner),writer),"preparation_owner");
  const auto sddl=L"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;"+writer+L")";Local descriptor;PACL acl=nullptr;BOOL present=FALSE,defaulted=FALSE;
  content::need(ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(),SDDL_REVISION_1,&descriptor.value,nullptr)&&GetSecurityDescriptorDacl(descriptor.value,&present,&acl,&defaulted)&&present&&acl,"preparation_acl");
  // 仅用于首次创建的空内容父目录；先检查为空，不能改写既有内容树的权限。
  auto empty=[&](){WIN32_FIND_DATAW data{};const HANDLE search=FindFirstFileW((current+L"\\*").c_str(),&data);if(search==INVALID_HANDLE_VALUE){content::need(GetLastError()==ERROR_FILE_NOT_FOUND,"preparation_directory");return;}
    bool vacant=true;DWORD error=0;do{const std::wstring name=data.cFileName;if(name!=L"."&&name!=L"..")vacant=false;}while(FindNextFileW(search,&data));error=GetLastError();FindClose(search);content::need(vacant&&error==ERROR_NO_MORE_FILES,"preparation_initialization_conflict");};
  empty();content::need(SetSecurityInfo(handle,SE_FILE_OBJECT,DACL_SECURITY_INFORMATION|PROTECTED_DACL_SECURITY_INFORMATION,nullptr,nullptr,acl,nullptr)==ERROR_SUCCESS,"preparation_acl");empty();parentAccess(handle,writer);
}
class Root {
  std::vector<std::unique_ptr<content::Handle>> ancestors;
  Local descriptor;PACL acl=nullptr;bool closed=false;
  void pinDirectory(const std::wstring& directoryPath){
    auto value=std::make_unique<content::Handle>(CreateFileW(directoryPath.c_str(),FILE_READ_ATTRIBUTES|FILE_LIST_DIRECTORY|READ_CONTROL,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    content::need(value->value!=INVALID_HANDLE_VALUE,"preparation_directory");content::inspect(value->value,true);ancestors.push_back(std::move(value));
  }
  std::wstring location(const std::wstring& relative){
    content::need(!closed,"preparation_closed");if(relative==L".")return path;
    content::need(relative.size()<=240&&relative.find_first_not_of(L"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/")==std::wstring::npos,"preparation_path");
    std::wstring result=path;for(const auto& part:content::parts(relative,L'/'))result+=L"\\"+part;return result;
  }
public:
  struct StorageIdentity {std::wstring volume,filesystem,serial,flags,maximumComponent,sectorsPerCluster,bytesPerSector;};
  std::wstring path,identity,writer;
  StorageIdentity storageIdentity() const {
    content::need(!closed&&!ancestors.empty(),"preparation_closed");const HANDLE handle=ancestors.back()->value;
    content::need(content::identity(handle)==identity,"preparation_identity");
    std::vector<wchar_t> finalName(32768);const DWORD count=GetFinalPathNameByHandleW(handle,finalName.data(),static_cast<DWORD>(finalName.size()),FILE_NAME_NORMALIZED|VOLUME_NAME_GUID);
    content::need(count>0&&count<finalName.size(),"preparation_volume_identity");
    const std::wstring finalPath(finalName.data(),count);const auto end=finalPath.find(L'}');
    content::need(finalPath.rfind(L"\\\\?\\Volume{",0)==0&&end!=std::wstring::npos&&end+1<finalPath.size()&&finalPath[end+1]==L'\\',"preparation_volume_identity");
    StorageIdentity result;result.volume=finalPath.substr(0,end+2);
    wchar_t filesystem[MAX_PATH]{};DWORD serial=0,maximum=0,flags=0;
    content::need(GetVolumeInformationByHandleW(handle,nullptr,0,&serial,&maximum,&flags,filesystem,MAX_PATH)!=0,"preparation_filesystem_identity");
    DWORD sectors=0,bytes=0,freeClusters=0,totalClusters=0;
    content::need(GetDiskFreeSpaceW(result.volume.c_str(),&sectors,&bytes,&freeClusters,&totalClusters)!=0&&sectors>0&&bytes>0,"preparation_volume_geometry");
    result.filesystem=filesystem;result.serial=std::to_wstring(serial);result.flags=std::to_wstring(flags);result.maximumComponent=std::to_wstring(maximum);
    result.sectorsPerCluster=std::to_wstring(sectors);result.bytesPerSector=std::to_wstring(bytes);return result;
  }
  std::wstring parentIdentity() const {
    content::need(!closed&&ancestors.size()>=2,"preparation_closed");return content::identity(ancestors[ancestors.size()-2]->value);
  }
  Root(std::wstring parent,const std::wstring& name,const std::vector<std::wstring>& readers,const std::wstring& expected=L""):writer(callerSid()){
    content::need(name.size()==36&&name.find_first_not_of(L"0123456789abcdef-")==std::wstring::npos&&readers.size()<=16,"preparation_argument");
    if(parent.rfind(L"\\\\?\\",0)==0)parent.erase(0,4);
    content::need(parent.size()>3&&((parent[0]>=L'A'&&parent[0]<=L'Z')||(parent[0]>=L'a'&&parent[0]<=L'z'))&&parent[1]==L':'&&parent[2]==L'\\'&&GetDriveTypeW(parent.substr(0,3).c_str())==DRIVE_FIXED,"preparation_local_root");
    std::wstring current=L"\\\\?\\"+parent.substr(0,3);pinDirectory(current);
    for(const auto& part:content::parts(parent.substr(3),L'\\')){if(current.back()!=L'\\')current+=L'\\';current+=part;pinDirectory(current);}
    parentAccess(ancestors.back()->value,writer);
    std::wstring sddl=L"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;"+writer+L")";std::set<std::wstring> unique;
    for(const auto& sid:readers){Local parsed;content::need(sid.size()<=184&&ConvertStringSidToSidW(sid.c_str(),&parsed.value)&&sidText(parsed.value)==sid&&!trusted(sid,writer)&&unique.insert(sid).second,"preparation_reader_sid");sddl+=L"(A;OICI;FRFX;;;"+sid+L")";}
    content::need(ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(),SDDL_REVISION_1,&descriptor.value,nullptr)!=0,"preparation_acl");BOOL present=FALSE,defaulted=FALSE;
    content::need(GetSecurityDescriptorDacl(descriptor.value,&present,&acl,&defaulted)&&present&&acl,"preparation_acl");
    path=current+L"\\"+name;SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES),descriptor.value,FALSE};
    if(expected.empty())content::need(CreateDirectoryW(path.c_str(),&security)!=0,"preparation_create");
    else content::need(expected.size()==48&&expected.find_first_not_of(L"0123456789abcdef")==std::wstring::npos,"preparation_identity");
    pinDirectory(path);identity=content::identity(ancestors.back()->value);
    content::need(expected.empty()||identity==expected,"preparation_identity");check(L".",true,expected.empty());
  }
  void check(const std::wstring& relative,bool directory,bool apply){
    std::vector<unsigned char> fileAcl;PACL desired=acl;
    if(!directory){fileAcl.resize(acl->AclSize);std::memcpy(fileAcl.data(),acl,acl->AclSize);desired=reinterpret_cast<PACL>(fileAcl.data());
      for(DWORD index=0;index<desired->AceCount;++index){void* ace=nullptr;content::need(GetAce(desired,index,&ace)!=0,"preparation_acl");static_cast<ACE_HEADER*>(ace)->AceFlags=0;}}
    const auto filename=location(relative);content::Handle file(CreateFileW(filename.c_str(),FILE_READ_ATTRIBUTES|READ_CONTROL|(apply?WRITE_DAC:0),FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    content::need(file.value!=INVALID_HANDLE_VALUE,"preparation_object");content::inspect(file.value,directory);
    if(relative==L".")content::need(content::identity(file.value)==identity,"preparation_identity");
    if(apply)content::need(SetSecurityInfo(file.value,SE_FILE_OBJECT,DACL_SECURITY_INFORMATION|PROTECTED_DACL_SECURITY_INFORMATION,nullptr,nullptr,desired,nullptr)==ERROR_SUCCESS,"preparation_acl");
    Local actual;PACL actualAcl=nullptr;PSID owner=nullptr;
    content::need(GetSecurityInfo(file.value,SE_FILE_OBJECT,OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,&owner,nullptr,&actualAcl,nullptr,&actual.value)==ERROR_SUCCESS&&actualAcl&&trusted(sidText(owner),writer),"preparation_acl");
    SECURITY_DESCRIPTOR_CONTROL control=0;DWORD revision=0;
    content::need(GetSecurityDescriptorControl(actual.value,&control,&revision)&&(control&SE_DACL_PROTECTED),"preparation_acl_protected");
    content::need(actualAcl->AceCount==desired->AceCount,"preparation_acl_count");
    for(DWORD index=0;index<desired->AceCount;++index){void* wanted=nullptr;void* observed=nullptr;content::need(GetAce(desired,index,&wanted)&&GetAce(actualAcl,index,&observed),"preparation_acl");
      const auto a=static_cast<ACCESS_ALLOWED_ACE*>(wanted),b=static_cast<ACCESS_ALLOWED_ACE*>(observed);
      content::need(a->Header.AceType==b->Header.AceType&&a->Header.AceSize==b->Header.AceSize,"preparation_acl_type");
      content::need(a->Header.AceFlags==b->Header.AceFlags,directory?"preparation_directory_acl_flags":"preparation_file_acl_flags");
      content::need(a->Mask==b->Mask,"preparation_acl_mask");content::need(EqualSid(&a->SidStart,&b->SidStart)!=0,"preparation_acl_sid");}
  }
  void flush(const std::wstring& relative,bool directory){
    try{
      check(relative,directory,false);const auto filename=location(relative);
      content::Handle file(CreateFileW(filename.c_str(),GENERIC_WRITE|FILE_READ_ATTRIBUTES|READ_CONTROL,FILE_SHARE_READ|FILE_SHARE_WRITE,
        nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
      content::need(file.value!=INVALID_HANDLE_VALUE,"preparation_flush_open");content::inspect(file.value,directory);
      if(relative==L".")content::need(content::identity(file.value)==identity,"preparation_identity");
      content::need(FlushFileBuffers(file.value)!=0,"preparation_flush_failed");
      content::inspect(file.value,directory);
    }catch(...){close();throw;}
  }
  std::wstring flushParent(){
    try{
      content::need(!closed&&ancestors.size()>=2,"preparation_closed");const HANDLE parent=ancestors[ancestors.size()-2]->value;
      const auto parentIdentity=content::identity(parent),parentPath=content::volumePath(parent);
      content::Handle file(CreateFileW(parentPath.c_str(),GENERIC_WRITE|FILE_READ_ATTRIBUTES|READ_CONTROL,FILE_SHARE_READ|FILE_SHARE_WRITE,
        nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
      content::need(file.value!=INVALID_HANDLE_VALUE,"preparation_flush_open");content::inspect(file.value,true);
      content::need(content::identity(file.value)==parentIdentity,"preparation_identity");parentAccess(file.value,writer);
      content::need(FlushFileBuffers(file.value)!=0,"preparation_flush_failed");return parentIdentity;
    }catch(...){close();throw;}
  }
  void close(){closed=true;ancestors.clear();}
};
}
