"""通过公开VFS诊断临时库重开；保留原生返回值与错误，不放宽恢复门槛。"""
import argparse,ctypes as C,hashlib,json,platform,sys
from pathlib import Path
import check_retired_cancel_durability as T
HERE=T.HERE;ROOT=T.ROOT
def inputs():return T.inputs()+[HERE/'check_windows_wal_reopen.py',HERE/'WINDOWS_WAL_REOPEN.md']
P=C.c_void_p
class VFS(C.Structure):
    _fields_=[('iVersion',C.c_int),('szOsFile',C.c_int),('mxPathname',C.c_int),('pNext',P),('zName',C.c_char_p),('pAppData',P)]+[(n,P) for n in ('xOpen','xDelete','xAccess','xFullPathname','xDlOpen','xDlError','xDlSym','xDlClose','xRandomness','xSleep','xCurrentTime','xGetLastError','xCurrentTimeInt64','xSetSystemCall','xGetSystemCall','xNextSystemCall')]
def run():
    assert sys.platform=='win32','本诊断仅适用于Windows；其他平台不得记作通过'
    library=Path(sys.base_prefix)/'DLLs/sqlite3.dll';lib=C.CDLL(str(library))
    lib.sqlite3_sourceid.restype=C.c_char_p;lib.sqlite3_libversion.restype=C.c_char_p
    source_id=lib.sqlite3_sourceid().decode();assert lib.sqlite3_libversion().decode()==T.sqlite3.sqlite_version
    db=T.sqlite3.connect(':memory:')
    try:assert db.execute('SELECT sqlite_source_id()').fetchone()[0]==source_id
    finally:db.close()
    lib.sqlite3_vfs_find.argtypes=[C.c_char_p];lib.sqlite3_vfs_find.restype=C.POINTER(VFS)
    v=lib.sqlite3_vfs_find(None);assert v and v.contents.iVersion==3 and v.contents.zName==b'win32'
    assert v.contents.xGetSystemCall and v.contents.xSetSystemCall
    get=C.CFUNCTYPE(P,P,C.c_char_p)(v.contents.xGetSystemCall);set_=C.CFUNCTYPE(C.c_int,P,C.c_char_p,P)(v.contents.xSetSystemCall)
    original=get(v,b'SetEndOfFile');assert original
    FN=C.WINFUNCTYPE(C.c_int,P,use_last_error=True);native=FN(original)
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.GetFinalPathNameByHandleW.argtypes=[P,C.c_wchar_p,C.c_uint32,C.c_uint32];kernel.GetFinalPathNameByHandleW.restype=C.c_uint32
    kernel.SetFilePointerEx.argtypes=[P,C.c_int64,C.POINTER(C.c_int64),C.c_uint32];kernel.SetFilePointerEx.restype=C.c_int
    events=[];observer_errors=[];context=None;attempts={};calls=0
    @FN
    def observe(handle):
        nonlocal calls
        result=native(handle);error=C.get_last_error();calls+=1
        try:
            if not result:
                buffer=C.create_unicode_buffer(32768);length=kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
                name=Path(buffer.value).name if 0<length<len(buffer) else ''
                position=C.c_int64();got=kernel.SetFilePointerEx(handle,0,C.byref(position),1)
                role={'case.sqlite':'database','case.sqlite-wal':'wal','case.sqlite-shm':'shm'}.get(name,'unknown')
                events.append(dict(context=context,winerror=error,file_role=role,requested_size=position.value if got else None))
        except Exception:observer_errors.append('native_observation_failed')
        finally:C.set_last_error(error)
        return result
    base=T.connect
    def connect(path):
        nonlocal context
        name=Path(path).parent.name
        allowed={m+'_'+p for m in ('DELETE','WAL') for p in ('after_member','after_seal','after_commit')}
        if name in allowed:
            attempts[name]=attempts.get(name,0)+1;context=dict(case=name,open_ordinal=attempts[name])
        else:context=None
        try:return base(path)
        finally:context=None
    assert set_(v,b'SetEndOfFile',C.cast(observe,P))==0
    try:
        T.connect=connect;checks,killed,errors=T.run()
    finally:
        T.connect=base;assert set_(v,b'SetEndOfFile',original)==0;assert get(v,b'SetEndOfFile')==original
    assert calls>0 and not observer_errors,'诊断未完整执行'
    return dict(all_passed=all(c['passed'] for c in checks),approved=False,cases_passed=sum(c['passed'] for c in checks),cases_failed=sum(not c['passed'] for c in checks),checks=checks,reopen_errors=errors,native_failures=events,native_calls=calls,observer_restored=True,observer_errors=observer_errors,diagnostic_scope='parent_test_process_only',python_version=platform.python_version(),sqlite_version=T.sqlite3.sqlite_version,sqlite_source_id=source_id,sqlite_library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),platform=platform.system(),vfs='win32',test_writer_terminations=killed,immediate_reopen_verified=not errors,production_runtime_verified=False,mapping_owner_identified=False,device_tests_executed=0)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');args=parser.parse_args()
    target=HERE/'windows-wal-reopen-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if args.check_report:
        report=json.loads(target.read_bytes());assert report['inputs']==hashes;print(json.dumps(dict(bindings_match=True,report_all_passed=report['all_passed'],matched_bindings=len(hashes))))
    else:
        report=run();report['inputs']=hashes
        if args.report:target.write_bytes(T.R.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
        if not report['all_passed']:raise SystemExit(1)
