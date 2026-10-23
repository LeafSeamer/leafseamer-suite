"""时间HTTP与完整设备IPC的设计生成器；不生成业务服务。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SID = "https://leafseamer.invalid/design/df03-service/time.schema.json"
IID = "https://leafseamer.invalid/design/df03-service/ipc.schema.json"
VERSION = "reference-time-service/0.1.0-draft.1"
IPC_VERSION = "ipc/0.8.0-reference-time-draft.1"
SOURCES = [
    "draft4/first-loop.schema.json", "c05-protection/protection.schema.json",
    "c05-protection/protocol.schema.json", "c09-panel-ipc/binding.schema.json",
    "c08-controller/execution-ipc.schema.json", "c08-controller/lifecycle.schema.json",
    "c02-command-view/command.schema.json", "c02-admission/admission.schema.json",
    "c02-cancellation/cancellation.schema.json", "c02-cancellation/ipc.schema.json",
    "c09-panel/channel-v02.schema.json",
    "df03-reference/reference.schema.json",
]
FEATURES = ("reference_bound_time", "reference_time_floor", "schedule_source_binding")


def encoded(v):
    return (json.dumps(v, ensure_ascii=False, indent=2) + "\n").encode()


def obj(**p):
    return dict(type="object", properties=p, required=list(p), additionalProperties=False)


def ref(n):
    return {"$ref": SID + "#/$defs/" + n}


def nullable(s):
    return {"anyOf": [s, {"type": "null"}]}


def enum(*values):
    return {"enum": list(values)}


def add(s, **fields):
    assert not set(fields) & set(s["properties"])
    s["properties"].update(fields)
    s["required"] += list(fields)


def remove(s, names):
    for n in names:
        del s["properties"][n]
        s["required"].remove(n)


def conditional(field, fields):
    return {"if": {"properties": {field: {"const": True}}, "required": [field]},
            "then": {"properties": fields},
            "else": {"properties": {n: {"type": "null"} for n in fields}}}


def local_models(time_id):
    r = lambda n: {"$ref": time_id + "#/$defs/" + n}
    d = {n: r(n) for n in ("Id", "Ref", "UInt", "Positive", "Signed", "Digest", "Interval", "Domain")}
    d["PublicClock"] = obj(model_id={"const": "reference-bound/1"},
        model_revision={"const": "1"}, observation_id=ref("Id"), service_id=ref("Id"),
        service_boot_id=ref("Id"), status=enum("conditional", "unavailable"),
        source_label=nullable(dict(type="string", minLength=1, maxLength=128)),
        source_authentication=enum("nts", "trusted_network", "unavailable"),
        reference_utc=nullable(ref("Interval")), estimated_utc_ns=nullable(ref("Signed")),
        error_radius_ns=nullable(ref("UInt")),
        reasons=dict(type="array", uniqueItems=True, maxItems=12,
            items=enum("clock_unavailable", "source_unavailable", "expired", "unqualified",
                       "storage_unavailable")),
        grants_execution={"const": False})
    d["PublicClock"]["allOf"] = [{
        "if": {"properties": {"status": {"const": "conditional"}}},
        "then": {"properties": {"source_label": dict(type="string", minLength=1, maxLength=128),
            "source_authentication": enum("nts", "trusted_network"), "reference_utc": ref("Interval"),
            "estimated_utc_ns": ref("Signed"), "error_radius_ns": ref("UInt"),
            "reasons": {"maxItems": 0}}},
        "else": {"properties": {"reference_utc": {"type": "null"},
            "estimated_utc_ns": {"type": "null"}, "error_radius_ns": {"type": "null"},
            "reasons": {"minItems": 1}}}}]
    d["EvidenceBundle"] = obj(bundle_id=ref("Id"), revision={"const": "1"},
        state_ref=ref("Ref"), source=r("Source"), profile=r("Profile"), policy=r("Policy"),
        approval=r("Approval"), request=r("Request"), authentication=r("AuthEvidence"),
        error=r("ErrorEvidence"), era=r("EraEvidence"), exchange=r("Exchange"),
        anchor=r("Anchor"), assessment=r("Assessment"), bundle_digest=ref("Digest"))
    d["ScheduleGuard"] = obj(guard_id=ref("Id"), revision={"const": "1"},
        origin_service_id=ref("Id"), origin_database_instance_id=ref("Id"),
        occurrence_ref=ref("Ref"), definition_artifact_ref=ref("Ref"),
        schedule_version=ref("Positive"), activation_ref=ref("Ref"), admission_ref=ref("Ref"),
        execution_id=ref("Id"), step_id=ref("Id"), step_window_ref=ref("Ref"),
        window=r("Window"), queue_deadline_tick_ns=ref("Positive"),
        local_clock_domain=ref("Domain"), guard_digest=ref("Digest"))
    d["ExecutionTime"] = obj(context_ref=ref("Ref"), utc_guard=r("UtcGuard"),
        schedule_ref=nullable(ref("Ref")))
    d["GateSnapshot"] = obj(snapshot_id=ref("Id"), domain=ref("Domain"), snapshot_revision=ref("Positive"),
        minimum_time_generation=ref("Positive"), state_ref=ref("Ref"),
        snapshot_digest=ref("Digest"))
    d["Error"] = obj(code=enum("invalid_request", "unauthenticated", "forbidden",
        "not_found", "digest_mismatch", "capacity", "unavailable"), retry_write={"const": False})
    for n, t in (("ClockResponse", ref("PublicClock")), ("BundleResponse", ref("EvidenceBundle")),
                 ("AnchorResponse", r("Anchor")), ("AssessmentResponse", r("Assessment")),
                 ("ProfileResponse", r("Profile"))):
        d[n] = obj(contract={"const": VERSION}, request_id=ref("Id"),
            service_id=ref("Id"), service_boot_id=ref("Id"), data=t)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SID,
        "title": VERSION, "x-approved": False, "not": {}, "$defs": d}


class Projection:
    """仅固定本地资源的具名defs闭包；业务const/enum/default不参与引用重写。"""
    def __init__(self, resources, output_id):
        self.resources = resources
        self.output_id = output_id
        self.names = {}
        self.defs = {}

    def project(self, value, base):
        if isinstance(value, list):
            return [self.project(x, base) for x in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for k, v in value.items():
            if k == "$ref":
                uri, pointer = v.split("#", 1)
                uri = uri or base
                assert pointer.startswith("/$defs/") and pointer.count("/") == 2, v
                n = pointer[7:]
                key = (uri, n)
                if key not in self.names:
                    assert uri in self.resources, uri
                    name = f"S{list(self.resources).index(uri)}__{n}"
                    self.names[key] = name
                    self.defs[name] = {}
                    self.defs[name] = self.project(self.resources[uri]["$defs"][n], uri)
                result[k] = "#/$defs/" + self.names[key]
            elif k in ("const", "enum", "default", "examples"):
                result[k] = copy.deepcopy(v)
            else:
                result[k] = self.project(v, base)
        return result

    def document(self, root, base):
        result = self.project(root, base)
        result["$defs"] = self.defs
        result["$id"] = self.output_id
        return result


def resources():
    return {json.loads((BASE / p).read_bytes())["$id"]: json.loads((BASE / p).read_bytes())
            for p in SOURCES}


def build_ipc(source, local):
    resources_ = copy.deepcopy(source)
    resources_[SID] = local
    ids = {p: json.loads((BASE / p).read_bytes())["$id"] for p in SOURCES}
    old_id = ids["c02-cancellation/ipc.schema.json"]
    cancel_id = ids["c02-cancellation/cancellation.schema.json"]
    time_id = ids["df03-reference/reference.schema.json"]
    rtime = lambda n: {"$ref": time_id + "#/$defs/" + n}
    # 每个历史来源的具名守卫均替换，不通过短名合并不同领域类型。
    for uri in (ids["draft4/first-loop.schema.json"], ids["c09-panel-ipc/binding.schema.json"],
                ids["c05-protection/protocol.schema.json"]):
        g = resources_[uri]["$defs"]["ExecutionGuard"]
        remove(g, ("clock_generation", "time_policy_revision", "clock_sample_ref",
                   "time_evidence_ref", "time_profile_ref"))
        g["allOf"] = [c for c in g.get("allOf", [])
                      if "time_required" not in c.get("if", {}).get("properties", {})]
        add(g, reference_time=nullable(ref("ExecutionTime")))
        g["allOf"].append(conditional("time_required", {"reference_time": ref("ExecutionTime")}))
    g = resources_[cancel_id]["$defs"]["Guard"]
    remove(g, ("time_evidence_ref", "time_policy_ref"))
    add(g, reference_time=nullable(ref("ExecutionTime")))
    g["allOf"] = [conditional("time_required", {"reference_time": ref("ExecutionTime")})]
    g["allOf"].append({"if": {"properties": {"time_required": {"const": True}}},
        "then": {"properties": {"reference_time": {"properties": {"schedule_ref": {"type": "null"}}}}}})
    cb = resources_[cancel_id]["$defs"]["CANCEL_GUARDBody"]
    add(cb, reference_context=nullable(ref("EvidenceBundle")))
    cb["allOf"] = [{"if": {"properties": {"guard": {"properties": {"time_required": {"const": True}}}}},
        "then": {"properties": {"reference_context": ref("EvidenceBundle")}},
        "else": {"properties": {"reference_context": {"type": "null"}}}}]
    ipc = resources_[old_id]
    d = ipc["$defs"]
    g = d["GUARD_INSTALLBody"]
    remove(g, ("clock_sample", "time_evidence", "time_profile"))
    g["properties"]["schedule_guard"] = nullable(ref("ScheduleGuard"))
    add(g, reference_context=nullable(ref("EvidenceBundle")))
    g["allOf"] = [{"if": {"properties": {"guard": {"properties": {"time_required": {"const": True}}}}},
        "then": {"properties": {"reference_context": ref("EvidenceBundle")}},
        "else": {"properties": {"reference_context": {"type": "null"}, "schedule_guard": {"type": "null"}}}}]
    add(d["GUARD_ACKBody"], reference_time_digest=nullable(ref("Digest")),
        schedule_guard_digest=nullable(ref("Digest")))
    add(resources_[cancel_id]["$defs"]["CANCEL_GUARD_ACKBody"], reference_time_digest=nullable(ref("Digest")))
    add(d["OPEN_GATEBody"], reference_time_snapshot=ref("GateSnapshot"))
    add(d["OPEN_GATE_ACKBody"], reference_time_snapshot_ref=ref("Ref"))
    for name in ("TIME_FENCEBody", "TIME_FENCE_ACKBody"):
        remove(d[name], ("time_policy_revision", "old_clock_generation", "new_clock_generation"))
    add(d["TIME_FENCEBody"], invalidation=rtime("Invalidation"))
    add(d["TIME_FENCE_ACKBody"], invalidation_ref=ref("Ref"), minimum_time_generation=ref("Positive"))
    for item in ipc["oneOf"]:
        frame = d[item["$ref"].split("/")[-1]]
        frame["properties"]["ipc_version"] = {"const": IPC_VERSION}
    d["HELLOBody"]["properties"]["supported_ipc_versions"]["items"] = {"const": IPC_VERSION}
    d["HELLO_ACKBody"]["properties"]["selected_ipc_version"] = {"const": IPC_VERSION}
    for name, field in (("HELLOBody", "supported_features"), ("HELLO_ACKBody", "selected_features")):
        d[name]["properties"][field]["allOf"] += [{"contains": {"const": f}} for f in FEATURES]
    root = {k: v for k, v in ipc.items() if k != "$defs"}
    root.update(title=IPC_VERSION, **{"x-approved": False, "x-runtime-approved": False})
    return Projection(resources_, IID).document(root, old_id)


ROUTES = [
    ("public", "/api/v1/clock", "getClock", "ClockResponse", None),
    ("public", "/api/v1/clock-assessment", "getClockAssessment", "ClockResponse", None),
    ("internal", "/internal/reference-time/bundles/{id}/{revision}", "getReferenceTimeBundle", "BundleResponse", "bundle"),
    ("internal", "/internal/reference-time/anchors/{id}/{revision}", "getReferenceTimeAnchor", "AnchorResponse", "anchor"),
    ("internal", "/internal/reference-time/assessments/{id}/{revision}", "getReferenceTimeAssessment", "AssessmentResponse", "assessment"),
    ("internal", "/internal/reference-time/profiles/{id}/{revision}", "getReferenceTimeProfile", "ProfileResponse", "profile"),
]


def openapi(audience, all_resources):
    projection = Projection(all_resources, SID)
    paths = {}
    for a, path, operation, response, kind in ROUTES:
        if a != audience:
            continue
        parameters = [dict(name="X-LeafSeamer-Contract", **{"in": "header"},
            required=True, schema={"const": VERSION, "type": "string"})]
        if kind:
            for n, location, model in (("id", "path", "Id"), ("revision", "path", "Positive"),
                                       ("digest", "query", "Digest")):
                parameters.append(dict(name=n, **{"in": location}, required=True,
                    schema=projection.project(ref(model), SID)))
        responses = {}
        for status in ("200", "400", "401", "403", "404", "409", "429", "503"):
            responses[status] = dict(description="精确查询结果" if status == "200" else "读取失败，不授权写重试",
                headers={"Cache-Control": dict(schema={"type": "string", "const": "no-store"})},
                content={"application/json": {"schema": projection.project(
                    ref(response if status == "200" else "Error"), SID)}})
        paths[path] = {"get": dict(operationId=operation, parameters=parameters, responses=responses,
            security=[{"humanBearer" if audience == "public" else "pairedMTLS": []}],
            **{"x-permission": "status.read" if audience == "public" else "clock.internal.read",
               "x-current-object-authorization-required": True})}
    # HTTP组件使用OpenAPI局部指针；仅已投影Schema节点存在引用。
    def components(v):
        if isinstance(v, list):
            return [components(x) for x in v]
        if not isinstance(v, dict):
            return v
        return {k: (x.replace("#/$defs/", "#/components/schemas/") if k == "$ref"
            else copy.deepcopy(x) if k in ("const", "enum", "examples", "default") else components(x))
            for k, x in v.items()}
    return {"openapi": "3.1.1", "info": {"title": "LeafSeamer参考时间" + audience, "version": VERSION},
        "x-approved": False, "paths": components(paths),
        "components": {"schemas": components(projection.defs), "securitySchemes": {
            "humanBearer": {"type": "http", "scheme": "bearer"}} if audience == "public" else {
            "pairedMTLS": {"type": "mutualTLS"}}}}


def build():
    source = resources()
    tid = json.loads((BASE / SOURCES[-1]).read_bytes())["$id"]
    local = local_models(tid)
    all_resources = {**source, SID: local}
    # 领域模型独立自包含；模型名保留便于明确选择验证入口。
    p = Projection(all_resources, SID)
    local_defs = {n: p.project(v, SID) for n, v in local["$defs"].items()}
    schema = {k: v for k, v in local.items() if k != "$defs"}
    schema["$defs"] = {**p.defs, **local_defs}
    manifest = {p: hashlib.sha256((BASE / p).read_bytes()).hexdigest() for p in SOURCES}
    return {"time.schema.json": schema, "ipc.schema.json": build_ipc(source, local),
        "public.openapi.json": openapi("public", all_resources),
        "internal.openapi.json": openapi("internal", all_resources),
        "source-bindings.json": {"approved": False, "sources": manifest,
            "http_operations": len(ROUTES), "ipc_frames": 46}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, value in build().items():
        if args.check:
            assert (HERE / name).read_bytes() == encoded(value), name
        else:
            (HERE / name).write_bytes(encoded(value))
