"""人工预期与合成映射检查；不运行业务服务或真实时钟。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from build_contracts import HERE, BASE, SOURCES, SID, VERSION, IPC_VERSION, FEATURES, build, encoded
import reference_model as M

ROOT = HERE.parents[2]


def isolated_fixture(folder, expression):
    script = ("import sys,json;sys.path.insert(0,sys.argv[1]);"
              "import check_contracts as C;"
              f"print(json.dumps(dict(value={expression},inputs=[str(p) for p in C.INPUTS])))")
    return json.loads(subprocess.check_output([sys.executable, "-c", script, str(BASE / folder)], cwd=ROOT))


def fixture():
    t = isolated_fixture("df03-reference", "C.fixture()")
    old = isolated_fixture("c02-cancellation", "C.fixtures()[0]")
    c, anchor, assessment, guard, invalidation = t["value"]
    bundle = M.T.seal(dict(bundle_id="bundle", revision="1",
        state_ref=M.T.object_ref(c["state"], "state_id", "state_digest"),
        **{n: copy.deepcopy(c[n]) for n in ("source", "profile", "policy", "approval", "request",
                                           "authentication", "error", "era", "exchange")},
        anchor=anchor, assessment=assessment), "bundle_digest")
    domain = copy.deepcopy(c["binding"]["domain"])
    r = lambda n: dict(id=n, revision="1", digest=M.T.digest(n))
    schedule = M.T.seal(dict(guard_id="schedule", revision="1", origin_service_id="seamer",
        origin_database_instance_id="seamer-db", occurrence_ref=r("occurrence"),
        definition_artifact_ref=r("definition"), schedule_version="1", activation_ref=r("activation"),
        admission_ref=r("admission"), execution_id="execution", step_id="step", step_window_ref=r("window"),
        window=copy.deepcopy(guard["window"]), queue_deadline_tick_ns="800000000",
        local_clock_domain=domain), "guard_digest")
    execution_time = dict(context_ref=M.T.object_ref(bundle, "bundle_id", "bundle_digest"),
        utc_guard=guard, schedule_ref=M.T.object_ref(schedule, "guard_id", "guard_digest"))
    snapshot = M.T.seal(dict(snapshot_id="gate-snapshot", domain=domain, snapshot_revision="1", minimum_time_generation="1",
        state_ref=bundle["state_ref"]), "snapshot_digest")
    c.update(required_time=True, runtime_valid=True, send_earliest="700000000", send_latest="800000000",
        minimum_time_generation="1", approved_execution_time=copy.deepcopy(execution_time),
        approved_schedule=copy.deepcopy(schedule), service_boot_id="controller-boot",
        approved_source_label="指定参考源",
        schedule_origin={n: copy.deepcopy(schedule[n]) for n in (
            "origin_service_id", "origin_database_instance_id", "occurrence_ref", "definition_artifact_ref",
            "schedule_version", "activation_ref", "admission_ref", "execution_id", "step_id", "step_window_ref")})
    frames = old["value"]
    for frame in frames.values():
        frame["ipc_version"] = IPC_VERSION
    for n, field in (("HELLO", "supported_features"), ("HELLO_ACK", "selected_features")):
        frames[n]["body"][field] += list(FEATURES)
    frames["HELLO"]["body"]["supported_ipc_versions"] = [IPC_VERSION]
    frames["HELLO_ACK"]["body"]["selected_ipc_version"] = IPC_VERSION
    b = frames["GUARD_INSTALL"]["body"]
    for n in ("clock_sample", "time_evidence", "time_profile"):
        del b[n]
    b.update(reference_context=copy.deepcopy(bundle), schedule_guard=copy.deepcopy(schedule))
    for n in ("clock_generation", "time_policy_revision", "clock_sample_ref",
              "time_evidence_ref", "time_profile_ref"):
        del b["guard"][n]
    b["guard"]["reference_time"] = copy.deepcopy(execution_time)
    b["guard"]["time_required"] = True
    M.T.seal(b["guard"], "guard_digest")
    frames["GUARD_ACK"]["body"].update(reference_time_digest=M.T.digest(execution_time),
        schedule_guard_digest=schedule["guard_digest"])
    cancel_time = copy.deepcopy(execution_time)
    cancel_time["schedule_ref"] = None
    b = frames["CANCEL_GUARD"]["body"]
    for n in ("time_evidence_ref", "time_policy_ref"):
        del b["guard"][n]
    b["guard"]["reference_time"] = cancel_time
    M.T.seal(b["guard"], "guard_digest")
    b["reference_context"] = copy.deepcopy(bundle)
    frames["CANCEL_GUARD_ACK"]["body"]["reference_time_digest"] = M.T.digest(cancel_time)
    frames["OPEN_GATE"]["body"]["reference_time_snapshot"] = snapshot
    frames["OPEN_GATE_ACK"]["body"]["reference_time_snapshot_ref"] = dict(
        id=snapshot["snapshot_id"], revision=snapshot["snapshot_revision"], digest=snapshot["snapshot_digest"])
    for n in ("TIME_FENCE", "TIME_FENCE_ACK"):
        b = frames[n]["body"]
        for k in ("time_policy_revision", "old_clock_generation", "new_clock_generation"):
            del b[k]
    frames["TIME_FENCE"]["body"]["invalidation"] = invalidation
    frames["TIME_FENCE_ACK"]["body"].update(
        invalidation_ref=M.T.object_ref(invalidation, "invalidation_id", "invalidation_digest"),
        minimum_time_generation="2")
    inputs = [Path(p) for p in t["inputs"] + old["inputs"]]
    return c, bundle, execution_time, schedule, snapshot, frames, inputs


def all_inputs(inherited):
    return list(dict.fromkeys(inherited + [BASE / p for p in SOURCES] + [
        HERE / n for n in ("README.md", "build_contracts.py", "reference_model.py", "check_contracts.py",
                           "time.schema.json", "ipc.schema.json", "public.openapi.json",
                           "internal.openapi.json", "source-bindings.json")]))


def run():
    results = []
    def check(name, actual, expected=None):
        assert actual == expected, (name, actual, expected)
        # 大型原件的完整相等断言已执行，报告保存比较结果而不重复铺陈原件。
        complex_value = isinstance(expected, (dict, list, set, tuple))
        results.append(dict(name=name, expected=True if complex_value else expected,
                            actual=True if complex_value else actual))
    artifacts = build()
    for n, value in artifacts.items():
        check("生成字节:" + n, (HERE / n).read_bytes() == encoded(value), True)
    schema, ipc = artifacts["time.schema.json"], artifacts["ipc.schema.json"]
    for s in (schema, ipc):
        Draft202012Validator.check_schema(s)
    for n in ("public.openapi.json", "internal.openapi.json"):
        validate(artifacts[n])
        check("OpenAPI:" + n, True, True)
    v = Draft202012Validator(ipc)
    valid = lambda n, value: Draft202012Validator({**schema, "not": False,
        "$ref": "#/$defs/" + n}).is_valid(value)
    # 上面的not:false撤销模型库根not:{}，具体defs才是实例验证入口。
    c, bundle, et, schedule, snapshot, frames, inherited = fixture()
    for n, value in (("EvidenceBundle", bundle), ("ExecutionTime", et), ("ScheduleGuard", schedule),
                     ("GateSnapshot", snapshot)):
        check("领域正例:" + n, valid(n, value), True)
    check("完整帧数", len(frames), 46)
    for n, frame in frames.items():
        check("IPC正例:" + n, v.is_valid(frame), True)
        bad = copy.deepcopy(frame)
        bad["ipc_version"] = "ipc/0.7.0-cancellation-draft.1"
        check("旧版本拒绝:" + n, v.is_valid(bad), False)
    for f in FEATURES:
        for name, field in (("HELLO", "supported_features"), ("HELLO_ACK", "selected_features")):
            bad = copy.deepcopy(frames[name])
            bad["body"][field].remove(f)
            check("缺特性:" + name + ":" + f, v.is_valid(bad), False)
    for name, old_field in (("GUARD_INSTALL", "time_evidence"), ("CANCEL_GUARD", "time_profile")):
        bad = copy.deepcopy(frames[name])
        bad["body"][old_field] = None
        check("拒绝旧载荷:" + name, v.is_valid(bad), False)
        bad = copy.deepcopy(frames[name]); bad["body"]["reference_context"] = None
        check("缺当前上下文:" + name, v.is_valid(bad), False)
        bad = copy.deepcopy(frames[name]); bad["body"]["guard"]["time_required"] = False
        check("即时夹带UTC:" + name, v.is_valid(bad), False)
        bad["body"]["guard"]["reference_time"] = None
        bad["body"]["reference_context"] = None
        if name == "GUARD_INSTALL":
            bad["body"]["schedule_guard"] = None
        check("即时无UTC:" + name, v.is_valid(bad), True)
    bad = copy.deepcopy(frames["GUARD_INSTALL"]); bad["body"]["schedule_guard"] = None
    bad["body"]["guard"]["reference_time"]["schedule_ref"] = None
    check("需要UTC但无排期可表达", v.is_valid(bad), True)
    bad = copy.deepcopy(frames["CANCEL_GUARD"])
    bad["body"]["guard"]["reference_time"]["schedule_ref"] = et["schedule_ref"]
    check("取消保护不能继承普通排期", v.is_valid(bad), False)
    # 自包含生成物不能再接受旧系统时间对象；普通与取消嵌套路径均检查。
    text = json.dumps(ipc)
    for forbidden in ("system-bound/1", "TimeBoundEvidence", "TimeBoundProfile", "ClockSample"):
        check("旧时间闭包不可达:" + forbidden, forbidden in text, False)
    def refs(node):
        if isinstance(node, list):
            return [r for x in node for r in refs(x)]
        if not isinstance(node, dict):
            return []
        return ([node["$ref"]] if "$ref" in node else []) + [
            r for k, x in node.items() if k not in ("const", "enum", "default", "examples") for r in refs(x)]
    for s in (schema, ipc):
        for r in refs(s):
            assert r.startswith("#/$defs/") and r[8:] in s["$defs"], r
    check("全部Schema引用本地闭合", True, True)
    public = artifacts["public.openapi.json"]
    internal = artifacts["internal.openapi.json"]
    check("HTTP声明数", (len(public["paths"]), len(internal["paths"])), (2, 4))
    for forbidden in ("EvidenceBundle", "Domain", "ErrorEvidence", "Approval", "runtime_binding_ref",
                      "request_bytes_ref", "response_bytes_ref", "database_instance_id"):
        check("公共闭包隔离:" + forbidden, forbidden in json.dumps(public), False)
    for path, item in internal["paths"].items():
        check("内部精确地址:" + path, {p["name"] for p in item["get"]["parameters"]},
              {"id", "revision", "digest", "X-LeafSeamer-Contract"})
    # 合成原件及权威明确给定，以下不模拟网络/签发/真实审批。
    check("完整Bundle", M.bundle_error(bundle, c))
    invalidation = frames["TIME_FENCE"]["body"]["invalidation"]
    fence_body = copy.deepcopy(frames["TIME_FENCE"]["body"])
    fence_body.update(clock_domain_id=c["binding"]["domain"]["clock_domain_id"],
                      descriptor_digest=c["binding"]["domain"]["descriptor_digest"])
    check("失效与屏障域一致", M.time_fence_error(fence_body, invalidation))
    bad = copy.deepcopy(fence_body); bad["clock_domain_id"] = "clock_" + "2" * 64
    check("失效与屏障错域拒绝", M.time_fence_error(bad, invalidation), "domain")
    bad = copy.deepcopy(fence_body); bad["invalidation"]["next_time_generation"] = "4"
    M.T.seal(bad["invalidation"], "invalidation_digest")
    check("重算失效摘要不代权威", M.time_fence_error(bad, invalidation), "authority")
    check("批准输入仍验精确后继", M.time_fence_error(bad, bad["invalidation"]), "generation")
    for kind, req, field, reason in (
        ("GUARD_ACK", "GUARD_INSTALL", "reference_time_digest", "time_digest"),
        ("CANCEL_GUARD_ACK", "CANCEL_GUARD", "reference_time_digest", "time_digest"),
        ("GUARD_ACK", "GUARD_INSTALL", "schedule_guard_digest", "schedule_digest"),
        ("OPEN_GATE_ACK", "OPEN_GATE", "reference_time_snapshot_ref", "snapshot"),
        ("TIME_FENCE_ACK", "TIME_FENCE", "invalidation_ref", "invalidation"),
        ("TIME_FENCE_ACK", "TIME_FENCE", "minimum_time_generation", "floor")):
        a, b = frames[kind]["body"], frames[req]["body"]
        check("新增回显正例:" + kind + ":" + field, M.time_ack_error(kind, a, b))
        z = copy.deepcopy(a); z[field] = None
        check("新增回显错配:" + kind + ":" + field, M.time_ack_error(kind, z, b), reason)
    ordinary = frames["GUARD_INSTALL"]["body"]["guard"]
    check("许可引用新Guard", M.guard_reference_error(ordinary["guard_id"], ordinary["guard_digest"], ordinary))
    check("许可旧摘要拒绝", M.guard_reference_error(ordinary["guard_id"], M.T.digest("old"), ordinary), "guard_reference")
    invoke = lambda cc=c, ee=et, bb=bundle, ss=schedule, now=700000100: M.execution_time_error(
        cc["required_time"], ee, bb, ss, cc, now)
    check("排期绑定正例", invoke())
    z = copy.deepcopy(c); z["minimum_time_generation"] = "2"
    check("已推进floor拒旧守卫", invoke(cc=z), "floor")
    z = copy.deepcopy(c); z["runtime_valid"] = False
    check("域无效", invoke(cc=z), "runtime")
    check("发送截止等号", invoke(now=800000000), "send_window")
    z = copy.deepcopy(c); z["send_latest"] = "9999999999"
    check("UTC子守卫截止等号", invoke(cc=z, now=800000100), "expired")
    check("发送时区间越界不复用安装结果", invoke(now=700000101), "window")
    z = copy.deepcopy(bundle); z["error"]["t3_error_ns"] = "1"; M.T.seal(z["error"], "error_digest")
    M.T.seal(z, "bundle_digest")
    zz = copy.deepcopy(et); zz["context_ref"] = M.T.object_ref(z, "bundle_id", "bundle_digest")
    cc = copy.deepcopy(c); cc["approved_execution_time"] = zz
    check("重算摘要不能替换误差原件", invoke(cc=cc, ee=zz, bb=z), "evidence")
    for field in c["schedule_origin"]:
        ss = copy.deepcopy(schedule)
        ss[field] = "2" if field == "schedule_version" else (
            {**ss[field], "id": "other"} if isinstance(ss[field], dict) else "other")
        M.T.seal(ss, "guard_digest")
        ee = copy.deepcopy(et); ee["schedule_ref"] = M.T.object_ref(ss, "guard_id", "guard_digest")
        cc = copy.deepcopy(c); cc.update(approved_schedule=ss, approved_execution_time=ee)
        check("重算摘要仍核排期来源:" + field, invoke(cc=cc, ee=ee, ss=ss), "schedule_origin")
    for field, value, reason in (
        ("window", {"not_before_utc_ns": "1599000000", "not_after_utc_ns": "1800000000"}, "schedule_window"),
        ("local_clock_domain", {**schedule["local_clock_domain"], "provider_boot_id": "other"}, "schedule_domain"),
        ("queue_deadline_tick_ns", "700000100", "queue_expired")):
        ss = copy.deepcopy(schedule); ss[field] = value; M.T.seal(ss, "guard_digest")
        ee = copy.deepcopy(et); ee["schedule_ref"] = M.T.object_ref(ss, "guard_id", "guard_digest")
        cc = copy.deepcopy(c); cc.update(approved_schedule=ss, approved_execution_time=ee)
        check("排期其他边界:" + field, invoke(cc=cc, ee=ee, ss=ss), reason)
    cc = copy.deepcopy(c); cc["required_time"] = False
    cc["runtime_clock_valid"] = False  # 即时动作不依赖UTC资格，但runtime_valid另验。
    check("即时无UTC仍可检查其他门控", invoke(cc=cc, ee=None, bb=None, ss=None))
    check("不能自行降低时间要求", M.execution_time_error(False, None, None, None, c, 700000100), "requirement")
    cc["runtime_valid"] = False
    check("即时不能绕域", invoke(cc=cc, ee=None, bb=None, ss=None), "runtime")
    for now, expected in ((700000100, "conditional"), (1600000100, "unavailable")):
        p = M.public_clock(c, now, "public-observation")
        check("公共状态:" + str(now), p["status"], expected)
        check("公共结构:" + str(now), valid("PublicClock", p), True)
        if expected == "conditional":
            check("独立中点预期", p["estimated_utc_ns"], "1650000000")
            check("独立误差预期", p["error_radius_ns"], "51000000")
        else:
            check("不可用不返回旧UTC", p["reference_utc"])
    p = M.public_clock(c, 700000100, "public-observation")
    p["provider_id"] = "internal"
    check("公共额外内部字段拒绝", valid("PublicClock", p), False)
    cold = copy.deepcopy(c); cold.update(stored_anchor=None, source=None, approved_source_label=None)
    p = M.public_clock(cold, 700000100, "cold-observation")
    check("冷启动无锚仍可表达状态", valid("PublicClock", p), True)
    check("冷启动无UTC", p["reference_utc"])
    current = copy.deepcopy(snapshot)
    new = copy.deepcopy(snapshot); new.update(snapshot_revision="2", minimum_time_generation="2")
    M.T.seal(new, "snapshot_digest")
    check("安装更强floor", M.install_floor(new, current, new), "installed")
    check("重复不变", M.install_floor(new, current, new), "duplicate")
    check("迟到开闸不降floor", M.install_floor(snapshot, current, snapshot), "stale")
    check("floor保留", current["minimum_time_generation"], "2")
    cc = dict(current_authenticated=True, current_object_authorized=True, service_id="controller")
    stored = dict(kind="bundle", ref=et["context_ref"], value=bundle)
    request = dict(service_id="controller", kind="bundle", **et["context_ref"])
    check("精确历史查原", M.exact_read(request, stored, cc), bundle)
    check("失去当前读取权", M.exact_read(request, stored, {**cc, "current_object_authorized": False}), "forbidden")
    check("跨authority不可见", M.exact_read({**request, "service_id": "seamer"}, stored, cc), "not_found")
    check("摘要错配拒绝", M.exact_read({**request, "digest": M.T.digest("wrong")}, stored, cc), "digest_mismatch")
    # const中的$ref必须保持实例原文，不能被投影器当成Schema引用。
    from build_contracts import Projection
    check("常量引用不重写", Projection({}, SID).project({"const": {"$ref": "opaque"}}, SID),
          {"const": {"$ref": "opaque"}})
    return results, all_inputs(inherited)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--check-report", action="store_true")
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error("--staged需配合--check-report")
    if args.check_report:
        read = (lambda p: subprocess.check_output(["git", "show", ":" + p.relative_to(ROOT).as_posix()],
                                                  cwd=ROOT)) if args.staged else Path.read_bytes
        report = json.loads(read(HERE / "reference-report.json"))
        # 仅读取上游声明的输入集合，不调用fixture或运行语义用例。
        inherited = [Path(p) for folder in ("df03-reference", "c02-cancellation")
                     for p in isolated_fixture(folder, "None")["inputs"]]
        assert set(report["inputs"]) == {p.relative_to(ROOT).as_posix() for p in all_inputs(inherited)}
        for p, sha in report["inputs"].items():
            path = ROOT / p
            assert path.resolve().is_relative_to(ROOT.resolve())
            assert hashlib.sha256(read(path)).hexdigest() == sha, p
        print(json.dumps(dict(all_passed=True, matched_bindings=len(report["inputs"]))))
    else:
        results, inputs = run()
        report = dict(all_passed=True, cases_passed=len(results), approved=False,
            scope="时间HTTP、46帧IPC结构及有限映射与floor快照",
            runtime_tests_executed=0, ntp_tests_executed=0, sqlite_tests_executed=0,
            device_tests_executed=0, checks=results,
            inputs={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
        if args.report:
            (HERE / "reference-report.json").write_bytes(encoded(report))
        print(json.dumps({k: v for k, v in report.items() if k not in ("checks", "inputs")}, ensure_ascii=False))
