"""将现行时间下界与完整恢复前态同库读取；不签发OPEN或执行许可。"""
import importlib.util
import command_snapshot_model as C
import supervisor_retirement_adoption_model as R

HERE = C.HERE
_spec = importlib.util.spec_from_file_location('controller_time_floor_source', HERE.parent/'df03-service/gate_snapshot_source_model.py')
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)
N = C.N
M = C.M


def for_open(db, recovery_id, fence_id, now, expected_provider_domain, retained=None):
    """expected_provider_domain仍需可信监督解析器提供，不能从外部请求取得。"""
    sources = C.for_open(db, recovery_id, fence_id, now)
    binding = sources['binding']
    runtime, _ = R.runtime(db, binding['writer_exit_id'])
    M.need(runtime['binding'] == binding, 'open_time_runtime_binding')
    snapshot = T.current(db, expected_provider_domain)
    # 同一Controller事务中精确解析已持久资源快照引用，不把placeholder洗成新引用。
    M.need(sources['originals']['resource']['time_snapshot_id'] == snapshot['snapshot_id'], 'open_time_snapshot_reference')
    target = dict(binding['scope'], clock_domain_id=binding['clock_domain_id'], descriptor_digest=binding['descriptor_digest'])
    T.for_open(db, snapshot, expected_provider_domain, target, retained)
    sources['reference_time_snapshot'] = snapshot
    sources['originals']['worker_runtime'] = runtime
    return sources
