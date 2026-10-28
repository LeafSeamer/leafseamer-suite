"""可信宿主的进程内失效串行边界；不含网络输出或权威事件监听。"""
import threading
import readset as R


class Dependency:
    __slots__=('_owner',)
    def __init__(self,owner):self._owner=owner


class ManagedReadSet:
    __slots__=('_owner',)
    def __init__(self,owner):self._owner=owner
    def ticket(self,provider):return self._owner._call(self,'ticket',provider)
    def provide(self,ticket,sources,fields):return self._owner._call(self,'provide',ticket,sources,fields)
    def seal(self):return self._owner._call(self,'seal')
    def consume(self,context,candidate):return self._owner._consume(self,context,candidate)
    def close(self):self._owner._close(self)


class Coordinator:
    """所有依赖失效必须先进入revoke；底层读集与权威不能另行交付。"""
    def __init__(self,*,max_reads=64,max_dependencies=256):
        R.need(type(max_reads) is int and 1<=max_reads<=64,'read_budget')
        R.need(type(max_dependencies) is int and 1<=max_dependencies<=256,'dependency_budget')
        self._lock=threading.RLock();self._reads={};self._dependencies={};self._building=0;self._retiring=0
        # 输出适配器的本地登记也属于同一失效边界；关闭仅改内存，不调用传输。
        self._outputs={}
        self._max_reads=max_reads;self._max_dependencies=max_dependencies;self._closed=False

    def register(self,revoker):
        R.need(callable(revoker),'dependency_revoker')
        with self._lock:
            R.need(not self._closed,'coordinator_closed')
            R.need(len(self._dependencies)+self._retiring<self._max_dependencies,'dependency_budget')
            token=Dependency(self);self._dependencies[token]=revoker;return token

    def begin(self,dependencies,build):
        # build只能构造新的未使用读集；保留名额后在锁外执行，撤权不等待构造。
        R.need(type(dependencies) in [list,tuple] and 1<=len(dependencies)<=16,'dependency_set')
        deps=tuple(dependencies)
        R.need(all(type(d) is Dependency for d in deps) and len(set(deps))==len(deps),'dependency_set')
        R.need(callable(build),'read_builder')
        handle=ManagedReadSet(self);raw=None;owned=False
        with self._lock:
            R.need(not self._closed,'coordinator_closed')
            R.need(all(d in self._dependencies for d in deps),'dependency_stale')
            R.need(sum(raw is not None for raw,_ in self._reads.values())+self._building<self._max_reads,'read_budget')
            self._reads[handle]=(None,deps);self._building+=1
        try:
            raw=build();R.need(type(raw) is R.ReadSet,'read_builder_result')
            with raw._lock:
                R.need(not hasattr(raw,'_coordinator_owner') and raw._state=='reading' and not raw._issued,'read_builder_fresh')
                raw._coordinator_owner=self;owned=True
            with self._lock:
                R.need(handle in self._reads and all(d in self._dependencies for d in deps),'dependency_stale')
                self._reads[handle]=(raw,deps)
            return handle
        except BaseException:
            with self._lock:self._drop(handle)
            if owned:raw.invalidate()
            raise
        finally:
            with self._lock:self._building-=1

    def _drop(self,handle):
        entry=self._reads.pop(handle,None)
        if entry is not None and entry[0] is not None:entry[0].invalidate()

    def _get(self,handle):
        R.need(type(handle) is ManagedReadSet and handle in self._reads,'managed_read_closed')
        raw,deps=self._reads[handle]
        R.need(raw is not None and all(d in self._dependencies for d in deps),'dependency_stale')
        return raw

    def _call(self,handle,method,*args):
        with self._lock:raw=self._get(handle)
        try:return getattr(raw,method)(*args)
        except BaseException:
            self._close(handle);raise

    def _consume(self,handle,context,candidate):
        # 与revoke共享同一锁；消费成功只是本地交付，不证明之后的入队资格。
        with self._lock:
            raw=self._get(handle)
            try:return raw.consume(context,candidate)
            finally:self._drop(handle)

    def _close(self,handle):
        with self._lock:self._drop(handle)

    def _close_output(self,output):
        output['closed']=True;output['queue'].clear();output['pending_deps']=();output['busy']=False

    def revoke(self,dependency):
        R.need(type(dependency) is Dependency and dependency._owner is self,'dependency_owner')
        with self._lock:
            callback=self._dependencies.pop(dependency,None)
            if callback is None:return False
            self._retiring+=1
            for handle,(_,deps) in list(self._reads.items()):
                if dependency in deps:self._drop(handle)
            for output in self._outputs.values():
                if dependency in output['deps'] or dependency in output['pending_deps'] or any(dependency in item['deps'] for item in output['queue']):self._close_output(output)
        # 先关闭全部本地读取，再清理外部权威；清理失败也不能恢复依赖。
        try:callback()
        except Exception as e:raise R.Unavailable('dependency_cleanup') from e
        finally:
            with self._lock:self._retiring-=1
        return True

    def close(self):
        with self._lock:
            self._closed=True;callbacks=list(self._dependencies.values());self._dependencies.clear();self._retiring+=len(callbacks)
            for handle in list(self._reads):self._drop(handle)
            for output in self._outputs.values():self._close_output(output)
        failed=False
        for callback in callbacks:
            try:callback()
            except Exception:failed=True
            finally:
                with self._lock:self._retiring-=1
        R.need(not failed,'dependency_cleanup')
