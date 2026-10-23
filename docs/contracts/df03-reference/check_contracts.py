"""人工预期、结构及有限参考模型验证；无网络、设备、产品实现。"""
import argparse
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
from jsonschema import Draft202012Validator
from build_contracts import HERE, SID, build, encoded
import reference_model as M

ROOT = HERE.parents[2]
INPUTS = [HERE / n for n in ("README.md", "build_contracts.py", "reference.schema.json",
                             "reference_model.py", "check_contracts.py")] + [
    ROOT / "docs/rebirth-df03-time-profile-design.md"]


def R(name):
    return dict(id=name, revision="1", digest=M.digest(name))


def clone(value):
    return copy.deepcopy(value)


def fixture(profile_patch=None, policy_patch=None):
    source = M.seal(dict(source_id="source", revision="1", configured_server_ref=R("server"),
        endpoint_set_ref=R("endpoints"), effective_config_ref=R("config"), authentication="nts",
        trust_policy_ref=R("trust")), "source_digest")
    profile = M.seal(dict(profile_id="profile", revision="1", model_id="reference-bound/1",
        model_revision="1", collector_artifact_ref=R("collector"), protocol_artifact_ref=R("protocol"),
        platform_qualification_ref=R("platform"), clock_method_ref=R("clock-method"),
        error_method_ref=R("error-method"), era_method_ref=R("era-method"),
        elapsed_model="observed-delta-relative/1", elapsed_error_ppm=0, span_quantization_ns="0",
        max_packet_bytes=1232, time_scale="posix-utc", leap_policy="normal-only", smear_policy="forbidden"),
        "profile_digest")
    profile.update(profile_patch or {})
    M.seal(profile, "profile_digest")
    policy = M.seal(dict(policy_id="policy", revision="1", max_exchange_span_ns="2000000000",
        max_exchange_age_ns="2000000000", max_anchor_age_ns="1000000000",
        max_upstream_age_ns="10000000000", max_half_width_ns="51000000"), "policy_digest")
    policy.update(policy_patch or {})
    M.seal(policy, "policy_digest")
    domain = dict(authority_service_id="controller", database_instance_id="database",
        provider_id="provider", provider_boot_id="provider-boot", runtime_binding_ref=R("runtime"),
        clock_domain_id="clock_" + "1" * 64, descriptor_digest=M.digest("descriptor"), clock_generation="1")
    approval = M.seal(dict(approval_id="approval", revision="1",
        profile_ref=M.object_ref(profile, "profile_id", "profile_digest"),
        source_ref=M.object_ref(source, "source_id", "source_digest"),
        qualification_ref=R("qualification"), authority_service_id="controller", status="approved"), "approval_digest")
    binding = dict(domain=domain, time_generation="1", profile_ref=approval["profile_ref"],
        source_ref=approval["source_ref"], approval_ref=M.object_ref(approval, "approval_id", "approval_digest"),
        policy_ref=M.object_ref(policy, "policy_id", "policy_digest"))
    request = M.seal(dict(request_id="request", revision="1", binding=binding,
        correlation_ref=R("correlation"), endpoint_ref=R("endpoint"), send_before_tick_ns="100",
        response_deadline_tick_ns="2000000100", request_bytes_ref=R("request-bytes"), request_size=160),
        "request_digest")
    request_ref = M.object_ref(request, "request_id", "request_digest")
    authentication = M.seal(dict(auth_id="authentication", revision="1", request_ref=request_ref,
        response_bytes_ref=R("response-bytes"), source_ref=binding["source_ref"], mode="nts",
        verification_ref=R("verification"), bootstrap_ref=R("independent-bootstrap"),
        peer_binding_ref=R("peer")), "authentication_digest")
    era = M.seal(dict(era_id="era", revision="1", request_ref=request_ref, response_bytes_ref=R("response-bytes"),
        method_ref=profile["era_method_ref"], independent_time_ref=R("coarse-independent"),
        allowed_utc=dict(lower_ns="0", upper_ns="10000000000")), "era_digest")
    error = M.seal(dict(error_id="error", revision="1", binding=binding, request_ref=request_ref,
        response_bytes_ref=R("response-bytes"), error_method_ref=profile["error_method_ref"],
        qualification_ref=R("server-error-qualification"), t2_error_ns="1000000", t3_error_ns="1000000",
        upstream_age_upper_at_m1_ns="3000000000", provenance_ref=R("upstream")), "error_digest")
    exchange = M.seal(dict(exchange_id="exchange", revision="1", binding=binding,
        request_ref=request_ref, correlation_ref=request["correlation_ref"], endpoint_ref=request["endpoint_ref"],
        response_bytes_ref=R("response-bytes"), response_size=160, receive_after_tick_ns="600000100",
        ntp_version=4, ntp_mode=4, leap=0, stratum=2, precision=-23,
        root_delay_word="655", root_dispersion_word="66",
        t2=dict(seconds="2208988801", fraction="0", era="0"),
        t3=dict(seconds="2208988801", fraction="2147483648", era="0"),
        authentication_ref=M.object_ref(authentication, "auth_id", "authentication_digest"),
        error_ref=M.object_ref(error, "error_id", "error_digest"),
        era_ref=M.object_ref(era, "era_id", "era_digest"), parser_receipt_ref=R("parser")), "exchange_digest")
    state = M.seal(dict(state_id="state", revision="1", binding=binding, status="collecting",
        current_anchor_ref=None, invalidation_ref=None), "state_digest")
    context = clone(dict(source=source, profile=profile, policy=policy, approval=approval, binding=binding,
        request=request, authentication=authentication, era=era, error=error, exchange=exchange, state=state,
        runtime_clock_valid=True, approval_current=True, source_current=True, correlation_verified=True,
        allowed_endpoints=[request["endpoint_ref"]], parser_receipt_ref=exchange["parser_receipt_ref"],
        parsed_fields={k: exchange[k] for k in M.HEADER_FIELDS}, response_bytes_ref=exchange["response_bytes_ref"],
        ordinary_utc_verified=True, authentication_verified=True, independent_bootstrap_valid=True,
        era_verified=True, error_verified=True, last_published_tick=None, commit_tick=600000100))
    anchor = M.derive_anchor(exchange, context, "anchor")
    context["stored_anchor"] = clone(anchor)
    context["state"].update(status="qualified", current_anchor_ref=M.object_ref(anchor, "anchor_id", "anchor_digest"))
    M.seal(context["state"], "state_digest")
    assessment = M.assess(anchor, context, 700000100, "assessment")
    guard = M.seal(dict(guard_id="guard", revision="1", model_id="reference-bound/1", model_revision="1",
        binding=binding, anchor_ref=M.object_ref(anchor, "anchor_id", "anchor_digest"),
        assessment_ref=M.object_ref(assessment, "assessment_id", "assessment_digest"),
        window=dict(not_before_utc_ns="1599000000", not_after_utc_ns="1701000001"),
        expires_tick_ns="800000100"), "guard_digest")
    context.update(stored_assessment=clone(assessment), approved_guard=clone(guard))
    invalidation = M.seal(dict(invalidation_id="invalidation", revision="1", old_binding=binding,
        next_time_generation="2", cause_ref=R("failure"), deny_new_utc_permits=True,
        protection_operation_ref=R("time-protection")), "invalidation_digest")
    return context, anchor, assessment, guard, invalidation


def run():
    cases = []
    def check(name, actual, expected=None):
        assert actual == expected, (name, actual, expected)
        cases.append(dict(name=name, expected=expected, observed=actual))
    schema = build()
    Draft202012Validator.check_schema(schema)
    check("生成物与唯一源一致", (HERE / "reference.schema.json").read_bytes() == encoded(schema), True)
    def valid(name, value):
        local = {**schema, "$ref": "#/$defs/" + name}
        local.pop("not")
        return Draft202012Validator(local).is_valid(value)
    c, anchor, assessment, guard, invalidation = fixture()
    for name, value in [
        ("Source", c["source"]), ("Profile", c["profile"]), ("Policy", c["policy"]),
        ("Approval", c["approval"]), ("Binding", c["binding"]), ("Request", c["request"]),
        ("AuthEvidence", c["authentication"]), ("ErrorEvidence", c["error"]), ("EraEvidence", c["era"]),
        ("Exchange", c["exchange"]), ("Anchor", anchor), ("Assessment", assessment),
        ("UtcGuard", guard), ("Invalidation", invalidation), ("AuthorityState", c["state"])]:
        check(name + "正例", valid(name, value), True)
        z = clone(value); z["unexpected"] = True
        check(name + "拒额外字段", valid(name, z), False)
    check("根不是实例入口", Draft202012Validator(schema).is_valid(anchor), False)
    for text in ("01", "-0", "+1", "1e3", "1\n", "1.0", " 1", "100000000000000000000"):
        z = clone(c["request"]); z["send_before_tick_ns"] = text
        check("计数拒绝" + repr(text), valid("Request", z), False)
    for name, field in (("Anchor", "model_id"), ("Profile", "model_id"), ("UtcGuard", "model_id")):
        z = clone({"Anchor": anchor, "Profile": c["profile"], "UtcGuard": guard}[name])
        z[field] = "system-bound/1"
        check(name + "不混旧模型", valid(name, z), False)
    z = clone(c["authentication"]); z["bootstrap_ref"] = None
    check("NTS结构必须有独立引导引用", valid("AuthEvidence", z), False)
    z["mode"] = "trusted_network"
    check("受信网络不伪造NTS引导", valid("AuthEvidence", z), True)
    z = clone(assessment); z.update(decision="unavailable", reasons=["expired"])
    check("失效不能仍给合格区间", valid("Assessment", z), False)
    z.update(utc=None, exchange_age_upper_ns=None, anchor_age_upper_ns=None, upstream_age_upper_ns=None)
    check("失效用null而非零", valid("Assessment", z), True)
    check("基础交换合格", M.exchange_error(c["exchange"], c))
    check("精确原始32位小数", str(M.stamp_ns(dict(seconds="2208988800", fraction="1", era="0"))), "1953125/8388608")
    check("时代回绕不截32位", str(M.stamp_ns(dict(seconds="1", fraction="0", era="1"))), "2085978497000000000")
    check("负纪元", str(M.stamp_ns(dict(seconds="2208988799", fraction="0", era="0"))), "-1000000000")
    check("TP39区间", M.interval_at_receive(1000000000, 1002000000, 1000000, 1000000, 20000000),
          dict(lower_ns="1001000000", upper_ns="1021000000"))
    check("TP40后续经过量区间", M.advance_interval(
        dict(lower_ns="1001000000", upper_ns="1021000000"), 99000000, 101000000),
        dict(lower_ns="1100000000", upper_ns="1122000000"))
    p = {**c["profile"], "elapsed_error_ppm": 100, "span_quantization_ns": "1000"}
    check("TP42外推上界", str(M.elapsed_bounds(20000000, p)[1]), "20003000")
    check("负下端向下舍入", M.floor(Fraction(-1, 10**6)), -1)
    check("毫秒上端向上舍入", M.ceil(Fraction(1021000001, 10**6)), 1022)
    check("基础锚点不用半RTT", anchor["utc_at_anchor"],
          dict(lower_ns="1499000000", upper_ns="1601000000"))
    check("后续UTC区间", assessment["utc"], dict(lower_ns="1599000000", upper_ns="1701000000"))
    check("交换年龄从m1", assessment["exchange_age_upper_ns"], "700000000")
    check("锚点年龄从m4", assessment["anchor_age_upper_ns"], "100000000")
    check("上游年龄仍增长", assessment["upstream_age_upper_ns"], "3700000000")
    noisy, noisy_anchor, noisy_assessment, _, _ = fixture(
        {"elapsed_error_ppm": 100, "span_quantization_ns": "1000"},
        {"max_half_width_ns": "51100000"})
    check("速率和量化计入采样上界", noisy_anchor["utc_at_anchor"],
          dict(lower_ns="1499000000", upper_ns="1601061000"))
    check("速率和量化计入后续区间", noisy_assessment["utc"],
          dict(lower_ns="1598989000", upper_ns="1701072000"))
    check("上游年龄使用经过量上界", noisy_assessment["upstream_age_upper_ns"], "3700071000")
    for label, policy_patch in [
        ("误差过宽", {"max_half_width_ns": "50999999"}),
        ("交换年龄等号", {"max_exchange_age_ns": "700000000"}),
        ("上游年龄等号", {"max_upstream_age_ns": "3700000000"})]:
        _, _, out, _, _ = fixture(policy_patch=policy_patch)
        check(label, out["reasons"], ["uncertainty" if label == "误差过宽" else "expired"])
    equal_span, _, _, _, _ = fixture(policy_patch={"max_exchange_span_ns": "600000000"})
    check("采样跨度等号可接受", M.exchange_error(equal_span["exchange"], equal_span))
    try:
        fixture(policy_patch={"max_exchange_span_ns": "599999999"})
    except ValueError as exc:
        check("跨度超过一纳秒拒绝", str(exc), "span")
    else:
        raise AssertionError("超跨度应拒绝")
    try:
        M.interval_at_receive(1000000000, 1025000000, 1000000, 1000000, 20000000)
    except ValueError as exc:
        check("TP41空区间拒绝", str(exc), "empty_interval")
    else:
        raise AssertionError("TP41应拒绝")
    for field, value, expected in [
        ("runtime_clock_valid", False, "runtime_clock"), ("approval_current", False, "approval"),
        ("source_current", False, "source"), ("correlation_verified", False, "correlation"),
        ("authentication_verified", False, "authentication"), ("independent_bootstrap_valid", False, "bootstrap"),
        ("era_verified", False, "era"), ("error_verified", False, "upstream"),
        ("ordinary_utc_verified", False, "leap_or_smear")]:
        check("交换拒绝" + field, M.exchange_error(c["exchange"], {**c, field: value}), expected)
    for field, value, expected in [
        ("ntp_version", 3, "packet"), ("ntp_mode", 3, "packet"), ("stratum", 0, "kod"),
        ("stratum", 16, "packet"), ("leap", 1, "leap_or_smear"), ("leap", 3, "leap_or_smear"),
        ("root_delay_word", "4294967296", "packet")]:
        z = clone(c["exchange"]); z[field] = value; M.seal(z, "exchange_digest")
        cc = clone(c); cc["parsed_fields"][field] = value
        check("报文字段" + field + str(value), M.exchange_error(z, cc), expected)
    for field, value, expected in [
        ("request_ref", R("other"), "request"), ("correlation_ref", R("other"), "correlation"),
        ("response_size", 1233, "capacity"), ("response_bytes_ref", R("other"), "parser"),
        ("receive_after_tick_ns", "99", "deadline"), ("receive_after_tick_ns", "2000000100", "deadline"),
        ("authentication_ref", R("other"), "authentication"), ("error_ref", R("other"), "error"),
        ("era_ref", R("other"), "era")]:
        z = clone(c["exchange"]); z[field] = value; M.seal(z, "exchange_digest")
        check("重算摘要仍拒错配" + field, M.exchange_error(z, c), expected)
    for stamp_field, value in [("fraction", "4294967296"), ("era", "2147483648"), ("seconds", "4294967296")]:
        z = clone(c["exchange"]); z["t3"][stamp_field] = value; M.seal(z, "exchange_digest")
        cc = clone(c); cc["parsed_fields"]["t3"] = clone(z["t3"])
        check("原始词宽" + stamp_field, M.exchange_error(z, cc), "era")
    cc = clone(c); cc["era"]["allowed_utc"]["upper_ns"] = "1499999999"
    M.seal(cc["era"], "era_digest")
    z = clone(c["exchange"]); z["era_ref"] = M.object_ref(cc["era"], "era_id", "era_digest"); M.seal(z, "exchange_digest")
    check("独立时代窗口不覆盖", M.exchange_error(z, cc), "era")
    for field, value, expected in [
        ("runtime_clock_valid", False, "runtime_clock"), ("approval_current", False, "approval"),
        ("source_current", False, "source"), ("error_verified", False, "evidence")]:
        out = M.assess(anchor, {**c, field: value}, 700000100, "bad")
        check("评估失效" + field, out["reasons"], [expected])
        check("失效结果形状" + field, valid("Assessment", out), True)
    check("年龄到等号拒绝", M.assess(anchor, c, 1600000100, "expired")["reasons"], ["expired"])
    check("时钟回退拒绝", M.assess(anchor, c, 600000099, "backwards")["reasons"], ["runtime_clock"])
    cc = clone(c); cc["error"]["upstream_age_upper_at_m1_ns"] = "0"; M.seal(cc["error"], "error_digest")
    check("评估不能换误差原件刷新年龄", M.assess(anchor, cc, 700000100, "wrong")["reasons"], ["evidence"])
    cc = clone(c); cc["binding"]["domain"]["provider_boot_id"] = "new-boot"
    check("新provider不继承旧锚点", M.assess(anchor, cc, 700000100, "restart")["reasons"], ["binding"])
    check("宿主wall诊断不参与区间", M.assess(anchor, {**c, "diagnostic_wall_ns": "-999999999"}, 700000100, "assessment"), assessment)
    check("误差上限等号可合格", assessment["decision"], "conditional")
    cc = clone(c); cc["policy"]["max_half_width_ns"] = "50999999"; M.seal(cc["policy"], "policy_digest")
    # 新policy须使用新绑定；旧锚点直接失效，不允许临时套新阈值。
    check("改变政策必须换绑定", M.assess(anchor, cc, 700000100, "policy")["reasons"], ["binding"])
    check("当前UTC守卫通过", M.guard_error(guard, assessment, anchor, c, 700000100))
    wrong_assessment = clone(assessment); wrong_assessment["anchor_ref"] = R("different-anchor")
    M.seal(wrong_assessment, "assessment_digest")
    wrong_guard = clone(guard)
    wrong_guard["assessment_ref"] = M.object_ref(wrong_assessment, "assessment_id", "assessment_digest")
    M.seal(wrong_guard, "guard_digest")
    check("同代同区间不能替换评估锚点", M.guard_error(wrong_guard, wrong_assessment, anchor,
        {**c, "approved_guard": wrong_guard, "stored_assessment": wrong_assessment}, 700000100), "assessment")
    z = clone(guard); z["window"]["not_after_utc_ns"] = "1701000000"; M.seal(z, "guard_digest")
    check("排期右端等号拒绝", M.guard_error(z, assessment, anchor, {**c, "approved_guard": z}, 700000100), "window")
    z = clone(guard); z["window"]["not_before_utc_ns"] = "1599000001"; M.seal(z, "guard_digest")
    check("区间左端不足拒绝", M.guard_error(z, assessment, anchor, {**c, "approved_guard": z}, 700000100), "window")
    check("发送时必须重新外推", M.guard_error(guard, assessment, anchor, c, 700000101), "window")
    check("单调守卫期限等号拒绝", M.guard_error(guard, assessment, anchor, c, 800000100), "expired")
    check("同摘要不能代替批准guard", M.guard_error(z, assessment, anchor, c, 700000100), "authority")
    check("有效旧区间不豁免当前撤销", M.guard_error(guard, assessment, anchor, {**c, "approval_current": False}, 700000100), "approval")
    collecting = clone(c["state"]); collecting.update(status="collecting", current_anchor_ref=None); M.seal(collecting, "state_digest")
    for fault in ("after_evidence", "before_commit"):
        state, ledger = clone(collecting), {}
        check("事务切点" + fault, M.publish(anchor, c["exchange"], c, state, ledger, "1", fault), "rolled_back")
        check("切点状态不变" + fault, state, collecting)
        check("切点无消费" + fault, ledger, {})
    state, ledger = clone(collecting), {}
    check("证据和当前指针原子发布", M.publish(anchor, c["exchange"], c, state, ledger, "1"), "committed")
    published = clone(state)
    check("重复响应只返回历史", M.publish(anchor, c["exchange"], c, state, ledger, "1"), "historical")
    check("重复不刷新修订或当前指针", state, published)
    z = clone(c["exchange"]); z["exchange_id"] = "replacement"; M.seal(z, "exchange_digest")
    check("同请求不能换交换身份", M.publish(anchor, z, c, state, ledger, "1"), "identity_conflict")
    state, ledger = clone(collecting), {}
    check("CAS竞争丢失不发布", M.publish(anchor, c["exchange"], c, state, ledger, "2"), "cas")
    check("较旧采样不能覆盖", M.publish(anchor, c["exchange"], {**c, "last_published_tick": 600000100}, state, ledger, "1"), "old_sample")
    check("提交前过期不发布", M.publish(anchor, c["exchange"], {**c, "commit_tick": 1600000100}, state, ledger, "1"), "expired_or_unqualified")
    check("过期事务无半边记录", (state, ledger), (collecting, {}))
    state = clone(c["state"])
    check("失效先关闭资格", M.invalidate(invalidation, state, "1"), "closed_pending_fence")
    check("失效推进代次", state["binding"]["time_generation"], "2")
    check("失效不保留当前锚点", state["current_anchor_ref"])
    check("失效状态格式", valid("AuthorityState", state), True)
    check("重复失效不二次推进", M.invalidate(invalidation, state, "1"), "cas")
    check("失效后不能提交旧采样", M.publish(anchor, c["exchange"], c, state, {}, "2"), "cas")
    cc = clone(c); cc["state"] = clone(c["state"]); cc["state"]["status"] = "unavailable"
    check("合格包不能绕失效状态", M.assess(anchor, cc, 700000100, "blocked")["reasons"], ["generation"])
    failure = M.seal(dict(failure_id="failure", revision="1", domain=c["binding"]["domain"], request_ref=None,
        observed_tick_ns="100", reason="capacity", diagnostic_ref=None), "failure_digest")
    check("无法建来源时只发布失败诊断", valid("Failure", failure), True)
    # 明确保留限制反证：合法Ref并不证明真实平台或上游误差。
    fake = clone(c["error"]); fake["provenance_ref"] = R("unverified-synthetic")
    M.seal(fake, "error_digest")
    check("结构合法不证明误差权威", valid("ErrorEvidence", fake), True)
    return cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--check-report", action="store_true")
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error("--staged需配合--check-report")
    if args.check_report:
        read = (lambda p: subprocess.check_output(["git", "show", ":" + p.relative_to(ROOT).as_posix()], cwd=ROOT)) if args.staged else Path.read_bytes
        report = json.loads(read(HERE / "reference-report.json"))
        assert set(report["inputs"]) == {p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:
            assert report["inputs"][p.relative_to(ROOT).as_posix()] == hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True, matched_bindings=len(INPUTS))))
    else:
        cases = run()
        report = dict(all_passed=True, cases_passed=len(cases), approved=False,
            scope="reference-bound/1字段及精确区间和有限发布失效模型",
            runtime_tests_executed=0, ntp_tests_executed=0, sqlite_tests_executed=0, device_tests_executed=0,
            checks=cases, inputs={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report:
            (HERE / "reference-report.json").write_bytes(encoded(report))
        print(json.dumps({k: v for k, v in report.items() if k not in ("checks", "inputs")}, ensure_ascii=False))
