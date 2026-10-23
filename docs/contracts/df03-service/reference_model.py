"""合成权威下的映射判定；不实现HTTP、IPC或设备发送。"""
import copy
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parent.parent / "df03-reference/reference_model.py"
_spec = importlib.util.spec_from_file_location("time_domain_model", _path)
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


def bundle_error(bundle, context):
    if not T.intact(bundle, "bundle_digest"):
        return "digest"
    for n in ("source", "profile", "policy", "approval", "request", "authentication",
              "error", "era", "exchange"):
        if bundle[n] != context[n]:
            return "evidence"
    if bundle["anchor"] != context["stored_anchor"] or bundle["assessment"] != context["stored_assessment"]:
        return "evidence"
    if bundle["state_ref"] != T.object_ref(context["state"], "state_id", "state_digest"):
        return "state"
    error = T.exchange_error(bundle["exchange"], context)
    if error:
        return error
    if T.derive_anchor(bundle["exchange"], context, bundle["anchor"]["anchor_id"]) != bundle["anchor"]:
        return "anchor"
    a = bundle["assessment"]
    if T.assess(bundle["anchor"], context, int(a["assessed_tick_ns"]), a["assessment_id"]) != a:
        return "assessment"


def execution_time_error(required, execution_time, bundle, schedule, context, now):
    # 需求由不可变命令/取消政策提供，不接受调用者自行降级。
    if required != context["required_time"]:
        return "requirement"
    if not context["runtime_valid"]:
        return "runtime"
    if not int(context["send_earliest"]) <= now < int(context["send_latest"]):
        return "send_window"
    if not required:
        return None if execution_time is bundle is schedule is None else "unexpected_time"
    if execution_time is None or bundle is None:
        return "missing_time"
    if execution_time != context["approved_execution_time"]:
        return "authority"
    if execution_time["context_ref"] != T.object_ref(bundle, "bundle_id", "bundle_digest"):
        return "context"
    error = bundle_error(bundle, context)
    if error:
        return error
    g = execution_time["utc_guard"]
    if int(g["binding"]["time_generation"]) < int(context["minimum_time_generation"]):
        return "floor"
    error = T.guard_error(g, bundle["assessment"], bundle["anchor"], context, now)
    if error:
        return error
    expected = context["approved_schedule"]
    if schedule != expected:
        return "schedule_authority"
    if schedule is None:
        return None if execution_time["schedule_ref"] is None else "schedule_ref"
    if not T.intact(schedule, "guard_digest"):
        return "schedule_digest"
    if execution_time["schedule_ref"] != T.object_ref(schedule, "guard_id", "guard_digest"):
        return "schedule_ref"
    if schedule["local_clock_domain"] != g["binding"]["domain"]:
        return "schedule_domain"
    if schedule["window"] != g["window"]:
        return "schedule_window"
    if now >= int(schedule["queue_deadline_tick_ns"]):
        return "queue_expired"
    for n, value in context["schedule_origin"].items():
        if schedule[n] != value:
            return "schedule_origin"


def public_clock(context, now, observation_id):
    a = (T.assess(context["stored_anchor"], context, now, "public-assessment")
         if context["stored_anchor"] is not None else
         dict(decision="unavailable", utc=None, reasons=["source"]))
    good = a["decision"] == "conditional"
    lo, hi = (int(a["utc"][n]) for n in ("lower_ns", "upper_ns")) if good else (0, 0)
    mid = (lo + hi) // 2
    return dict(model_id="reference-bound/1", model_revision="1", observation_id=observation_id,
        service_id=context["binding"]["domain"]["authority_service_id"],
        service_boot_id=context["service_boot_id"], status="conditional" if good else "unavailable",
        source_label=context["approved_source_label"],
        source_authentication=context["source"]["authentication"] if context["source"] else "unavailable",
        reference_utc=copy.deepcopy(a["utc"]) if good else None,
        estimated_utc_ns=str(mid) if good else None,
        error_radius_ns=str(max(mid - lo, hi - mid)) if good else None,
        reasons=[] if good else ["expired" if a["reasons"] == ["expired"] else "unqualified"],
        grants_execution=False)


def exact_read(request, stored, context):
    # 读取旧证据不要求旧profile仍获批准，但要求现在有权读取这个对象。
    if not context["current_authenticated"]:
        return "unauthenticated"
    if not context["current_object_authorized"]:
        return "forbidden"
    if request["service_id"] != context["service_id"] or request["kind"] != stored["kind"]:
        return "not_found"
    if request["id"] != stored["ref"]["id"] or request["revision"] != stored["ref"]["revision"]:
        return "not_found"
    if request["digest"] != stored["ref"]["digest"]:
        return "digest_mismatch"
    return copy.deepcopy(stored["value"])


def install_floor(snapshot, current, approved):
    if snapshot != approved or not T.intact(snapshot, "snapshot_digest"):
        return "authority"
    if snapshot["domain"] != current["domain"]:
        return "domain"
    old_rev, rev = int(current["snapshot_revision"]), int(snapshot["snapshot_revision"])
    if rev < old_rev or int(snapshot["minimum_time_generation"]) < int(current["minimum_time_generation"]):
        return "stale"
    if rev == old_rev:
        return "duplicate" if snapshot == current else "identity_conflict"
    current.clear()
    current.update(copy.deepcopy(snapshot))
    return "installed"


def time_ack_error(kind, ack, request):
    """仅新增时间回显；原消息方向/序号/尝试/完整cut另由既有协议验证。"""
    if kind in ("GUARD_ACK", "CANCEL_GUARD_ACK"):
        g = request["guard"]
        expected = T.digest(g["reference_time"]) if g["time_required"] else None
        if ack["reference_time_digest"] != expected:
            return "time_digest"
        if kind == "GUARD_ACK":
            schedule = request["schedule_guard"]
            if ack["schedule_guard_digest"] != (schedule["guard_digest"] if schedule else None):
                return "schedule_digest"
    elif kind == "OPEN_GATE_ACK":
        snapshot = request["reference_time_snapshot"]
        expected = dict(id=snapshot["snapshot_id"], revision=snapshot["snapshot_revision"],
                        digest=snapshot["snapshot_digest"])
        if ack["reference_time_snapshot_ref"] != expected:
            return "snapshot"
    elif kind == "TIME_FENCE_ACK":
        invalidation = request["invalidation"]
        if ack["invalidation_ref"] != T.object_ref(invalidation, "invalidation_id", "invalidation_digest"):
            return "invalidation"
        if ack["minimum_time_generation"] != invalidation["next_time_generation"]:
            return "floor"
    else:
        raise ValueError("unknown_kind")


def guard_reference_error(guard_id, guard_digest, guard):
    if guard_id != guard["guard_id"] or guard_digest != guard["guard_digest"] or not T.intact(guard, "guard_digest"):
        return "guard_reference"


def time_fence_error(body, approved_invalidation):
    i = body["invalidation"]
    if i != approved_invalidation or not T.intact(i, "invalidation_digest"):
        return "authority"
    domain = i["old_binding"]["domain"]
    if any(body[n] != domain[n] for n in ("clock_domain_id", "descriptor_digest")):
        return "domain"
    if int(i["next_time_generation"]) != int(i["old_binding"]["time_generation"]) + 1:
        return "generation"
