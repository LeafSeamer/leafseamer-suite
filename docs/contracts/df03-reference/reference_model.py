"""有限参考判定与有理数算术；不采集NTP、不修改时钟、不提供真实权威。"""
import copy
from fractions import Fraction
import hashlib
import rfc8785

NTP_UNIX_SECONDS = 2208988800
U32 = 2**32
HEADER_FIELDS = ("ntp_version", "ntp_mode", "leap", "stratum", "precision",
                 "root_delay_word", "root_dispersion_word", "t2", "t3")


def digest(value):
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def seal(value, field):
    value[field] = digest({k: v for k, v in value.items() if k != field})
    return value


def intact(value, field):
    return value[field] == digest({k: v for k, v in value.items() if k != field})


def object_ref(value, id_field, digest_field):
    return dict(id=value[id_field], revision=value["revision"], digest=value[digest_field])


def floor(value):
    value = Fraction(value)
    return value.numerator // value.denominator


def ceil(value):
    return -floor(-value)


def stamp_ns(stamp):
    seconds, fraction, era = (int(stamp[k]) for k in ("seconds", "fraction", "era"))
    if not (0 <= seconds < U32 and 0 <= fraction < U32 and -(2**31) <= era < 2**31):
        raise ValueError("stamp_range")
    return (era * U32 + seconds - NTP_UNIX_SECONDS) * 10**9 + Fraction(fraction * 10**9, U32)


def elapsed_bounds(delta, profile):
    if delta < 0:
        raise ValueError("backwards")
    rate = Fraction(profile["elapsed_error_ppm"], 10**6)
    quantum = int(profile["span_quantization_ns"])
    # 已由平台资格证明：这里是相对已观测delta的经过量包络，不是振荡器频率误差。
    return max(Fraction(0), delta * (1 - rate) - quantum), delta * (1 + rate) + quantum


def interval_at_receive(t2, t3, e2, e3, elapsed_upper):
    lower, upper = floor(t3 - e3), ceil(t2 + e2 + elapsed_upper)
    if lower > upper:
        raise ValueError("empty_interval")
    return dict(lower_ns=str(lower), upper_ns=str(upper))


def advance_interval(interval, elapsed_lower, elapsed_upper):
    return dict(lower_ns=str(floor(int(interval["lower_ns"]) + elapsed_lower)),
                upper_ns=str(ceil(int(interval["upper_ns"]) + elapsed_upper)))


def refs(context):
    return {
        "source_ref": object_ref(context["source"], "source_id", "source_digest"),
        "profile_ref": object_ref(context["profile"], "profile_id", "profile_digest"),
        "policy_ref": object_ref(context["policy"], "policy_id", "policy_digest"),
        "approval_ref": object_ref(context["approval"], "approval_id", "approval_digest"),
    }


def binding_error(binding, context):
    if binding != context["binding"]:
        return "binding"
    if any(binding[k] != v for k, v in refs(context).items()):
        return "binding"
    if not context["runtime_clock_valid"]:
        return "runtime_clock"
    for obj, field in (("profile", "profile_digest"), ("policy", "policy_digest"),
                       ("source", "source_digest"), ("approval", "approval_digest")):
        if not intact(context[obj], field):
            return "evidence"
    approval = context["approval"]
    if (approval["status"] != "approved" or not context["approval_current"] or
        approval["profile_ref"] != binding["profile_ref"] or approval["source_ref"] != binding["source_ref"] or
        approval["authority_service_id"] != binding["domain"]["authority_service_id"]):
        return "approval"
    if not context["source_current"]:
        return "source"
    return None


def exchange_error(exchange, context):
    x = exchange
    r, p, policy = (context[k] for k in ("request", "profile", "policy"))
    error = binding_error(x["binding"], context)
    if error:
        return error
    if r["binding"] != x["binding"] or not intact(x, "exchange_digest") or not intact(r, "request_digest"):
        return "binding"
    if x["request_ref"] != object_ref(r, "request_id", "request_digest"):
        return "request"
    if x["correlation_ref"] != r["correlation_ref"] or x["endpoint_ref"] != r["endpoint_ref"]:
        return "correlation"
    if not context["correlation_verified"] or x["endpoint_ref"] not in context["allowed_endpoints"]:
        return "correlation"
    if not (48 <= x["response_size"] <= p["max_packet_bytes"] and
            48 <= r["request_size"] <= p["max_packet_bytes"]):
        return "capacity"
    if (x["parser_receipt_ref"] != context["parser_receipt_ref"] or
        {k: x[k] for k in HEADER_FIELDS} != context["parsed_fields"] or
        x["response_bytes_ref"] != context["response_bytes_ref"]):
        return "parser"
    if x["ntp_version"] != 4 or x["ntp_mode"] != 4:
        return "packet"
    if x["stratum"] == 0:
        return "kod"
    if not 1 <= x["stratum"] <= 15:
        return "packet"
    if x["leap"] != 0 or not context["ordinary_utc_verified"]:
        return "leap_or_smear"
    if not all(0 <= int(x[k]) < U32 for k in ("root_delay_word", "root_dispersion_word")):
        return "packet"
    auth, era, bound = (context[k] for k in ("authentication", "era", "error"))
    for role, obj, id_field, hash_field in (
        ("authentication", auth, "auth_id", "authentication_digest"),
        ("era", era, "era_id", "era_digest"), ("error", bound, "error_id", "error_digest")):
        if not intact(obj, hash_field) or x[role + "_ref"] != object_ref(obj, id_field, hash_field):
            return role
        if obj["request_ref"] != x["request_ref"] or obj["response_bytes_ref"] != x["response_bytes_ref"]:
            return role
    if auth["source_ref"] != x["binding"]["source_ref"] or auth["mode"] != context["source"]["authentication"]:
        return "authentication"
    if not context["authentication_verified"]:
        return "authentication"
    if auth["mode"] == "nts" and (auth["bootstrap_ref"] is None or not context["independent_bootstrap_valid"]):
        return "bootstrap"
    if not context["era_verified"] or era["method_ref"] != p["era_method_ref"]:
        return "era"
    if not context["error_verified"] or bound["binding"] != x["binding"] or bound["error_method_ref"] != p["error_method_ref"]:
        return "upstream"
    try:
        t2, t3 = stamp_ns(x["t2"]), stamp_ns(x["t3"])
    except ValueError:
        return "era"
    lo, hi = (int(era["allowed_utc"][k]) for k in ("lower_ns", "upper_ns"))
    if lo > hi or not (lo <= t2 <= t3 <= hi):
        return "era"
    if any(int(x[k]["seconds"]) == 0 and int(x[k]["fraction"]) == 0 for k in ("t2", "t3")):
        return "packet"
    m1, m4 = int(r["send_before_tick_ns"]), int(x["receive_after_tick_ns"])
    if m4 < m1 or not m4 < int(r["response_deadline_tick_ns"]):
        return "deadline"
    elapsed = elapsed_bounds(m4 - m1, p)[1]
    if elapsed > int(policy["max_exchange_span_ns"]):
        return "span"
    if elapsed >= int(policy["max_exchange_age_ns"]):
        return "expired"
    if int(bound["upstream_age_upper_at_m1_ns"]) + ceil(elapsed) >= int(policy["max_upstream_age_ns"]):
        return "upstream"
    try:
        interval_at_receive(t2, t3, int(bound["t2_error_ns"]), int(bound["t3_error_ns"]), elapsed)
    except ValueError:
        return "invalid_interval"
    return None


def derive_anchor(exchange, context, anchor_id):
    error = exchange_error(exchange, context)
    if error:
        raise ValueError(error)
    r, p, e = (context[k] for k in ("request", "profile", "error"))
    m1, m4 = int(r["send_before_tick_ns"]), int(exchange["receive_after_tick_ns"])
    interval = interval_at_receive(stamp_ns(exchange["t2"]), stamp_ns(exchange["t3"]),
        int(e["t2_error_ns"]), int(e["t3_error_ns"]), elapsed_bounds(m4 - m1, p)[1])
    derivation = dict(exchange_ref=object_ref(exchange, "exchange_id", "exchange_digest"),
        request_ref=object_ref(r, "request_id", "request_digest"), **refs(context),
        authentication_ref=exchange["authentication_ref"], error_ref=exchange["error_ref"],
        era_ref=exchange["era_ref"], formula="reference-bound/1:observed-delta-relative/1")
    return seal(dict(anchor_id=anchor_id, revision="1", model_id="reference-bound/1", model_revision="1",
        binding=copy.deepcopy(exchange["binding"]), exchange_ref=derivation["exchange_ref"],
        anchor_tick_ns=str(m4), exchange_start_tick_ns=str(m1), utc_at_anchor=interval,
        derivation_digest=digest(derivation)), "anchor_digest")


def assess(anchor, context, now, assessment_id):
    result = dict(assessment_id=assessment_id, revision="1", model_id="reference-bound/1", model_revision="1",
        binding=copy.deepcopy(anchor["binding"]), anchor_ref=object_ref(anchor, "anchor_id", "anchor_digest"),
        assessed_tick_ns=str(now), utc=None, exchange_age_upper_ns=None, anchor_age_upper_ns=None,
        upstream_age_upper_ns=None, decision="unavailable", reasons=[])
    error = binding_error(anchor["binding"], context)
    if not error and (anchor != context["stored_anchor"] or not intact(anchor, "anchor_digest")):
        error = "evidence"
    if not error and context["state"]["status"] != "qualified":
        error = "generation"
    if not error and context["state"]["binding"] != anchor["binding"]:
        error = "binding"
    if not error and not context["error_verified"]:
        error = "evidence"
    if not error and (anchor["exchange_ref"] != object_ref(context["exchange"], "exchange_id", "exchange_digest") or
        context["exchange"]["error_ref"] != object_ref(context["error"], "error_id", "error_digest") or
        context["error"]["binding"] != anchor["binding"] or not intact(context["error"], "error_digest")):
        error = "evidence"
    if not error and (now < int(anchor["anchor_tick_ns"]) or
                      now < int(anchor["exchange_start_tick_ns"])):
        error = "runtime_clock"
    if not error:
        p, policy = context["profile"], context["policy"]
        low, high = elapsed_bounds(now - int(anchor["anchor_tick_ns"]), p)
        exchange_age = ceil(elapsed_bounds(now - int(anchor["exchange_start_tick_ns"]), p)[1])
        anchor_age = ceil(high)
        upstream_age = int(context["error"]["upstream_age_upper_at_m1_ns"]) + exchange_age
        utc = advance_interval(anchor["utc_at_anchor"], low, high)
        if (exchange_age >= int(policy["max_exchange_age_ns"]) or
            anchor_age >= int(policy["max_anchor_age_ns"]) or
            upstream_age >= int(policy["max_upstream_age_ns"])):
            error = "expired"
        elif int(utc["lower_ns"]) > int(utc["upper_ns"]):
            error = "invalid_interval"
        elif int(utc["upper_ns"]) - int(utc["lower_ns"]) > 2 * int(policy["max_half_width_ns"]):
            error = "uncertainty"
        else:
            result.update(utc=utc, exchange_age_upper_ns=str(exchange_age),
                anchor_age_upper_ns=str(anchor_age), upstream_age_upper_ns=str(upstream_age),
                decision="conditional")
    if error:
        result["reasons"] = [error]
    return seal(result, "assessment_digest")


def guard_error(guard, assessment, anchor, context, now):
    if not intact(guard, "guard_digest"):
        return "digest"
    if guard != context["approved_guard"]:
        return "authority"
    if guard["binding"] != anchor["binding"] or guard["anchor_ref"] != object_ref(anchor, "anchor_id", "anchor_digest"):
        return "binding"
    if guard["assessment_ref"] != object_ref(assessment, "assessment_id", "assessment_digest"):
        return "assessment"
    if assessment != context["stored_assessment"] or not intact(assessment, "assessment_digest"):
        return "assessment"
    if (assessment["decision"] != "conditional" or assessment["binding"] != anchor["binding"] or
        assessment["anchor_ref"] != guard["anchor_ref"]):
        return "assessment"
    if int(assessment["assessed_tick_ns"]) > now or now >= int(guard["expires_tick_ns"]):
        return "expired"
    # 不能复用旧评估区间作为实际发送时刻；每次按当前tick重新外推并验证资格。
    current = assess(anchor, context, now, "guard-evaluation")
    if current["decision"] != "conditional":
        return current["reasons"][0]
    window = guard["window"]
    before, after = int(window["not_before_utc_ns"]), int(window["not_after_utc_ns"])
    if not before < after:
        return "window"
    if not (before <= int(current["utc"]["lower_ns"]) and int(current["utc"]["upper_ns"]) < after):
        return "window"
    return None


def publish(anchor, exchange, context, state, ledger, expected_revision, fault=None):
    """字典副本模拟单writer事务；未执行SQLite或真实并发。"""
    domain = exchange["binding"]["domain"]
    key = tuple(domain[k] for k in ("authority_service_id", "database_instance_id", "provider_id",
                                    "provider_boot_id")) + (context["request"]["request_id"],)
    if key in ledger:
        return "historical" if ledger[key]["exchange_digest"] == exchange["exchange_digest"] else "identity_conflict"
    if state["revision"] != expected_revision or state["binding"] != context["binding"]:
        return "cas"
    if state["status"] not in ("collecting", "qualified"):
        return "closed"
    if exchange_error(exchange, context):
        return "unqualified"
    if anchor != derive_anchor(exchange, context, anchor["anchor_id"]):
        return "derivation"
    if context["last_published_tick"] is not None and int(anchor["anchor_tick_ns"]) <= context["last_published_tick"]:
        return "old_sample"
    if int(state["revision"]) >= 10**20 - 1:
        return "exhausted"
    candidate = copy.deepcopy(state)
    entries = copy.deepcopy(ledger)
    entries[key] = dict(exchange_digest=exchange["exchange_digest"], anchor=copy.deepcopy(anchor))
    if fault == "after_evidence":
        return "rolled_back"
    candidate.update(revision=str(int(candidate["revision"]) + 1), status="qualified",
                     current_anchor_ref=object_ref(anchor, "anchor_id", "anchor_digest"))
    seal(candidate, "state_digest")
    assessment_context = {**context, "state": candidate, "stored_anchor": anchor, "exchange": exchange}
    if assess(anchor, assessment_context, context["commit_tick"], "publication-check")["decision"] != "conditional":
        return "expired_or_unqualified"
    if fault == "before_commit":
        return "rolled_back"
    state.clear()
    state.update(candidate)
    ledger.clear()
    ledger.update(entries)
    return "committed"


def invalidate(record, state, expected_revision):
    if not intact(record, "invalidation_digest"):
        return "digest"
    if state["revision"] != expected_revision or record["old_binding"] != state["binding"]:
        return "cas"
    if int(record["next_time_generation"]) != int(state["binding"]["time_generation"]) + 1:
        return "generation"
    if int(record["next_time_generation"]) >= 10**20 or int(state["revision"]) >= 10**20 - 1:
        return "exhausted"
    state["binding"] = copy.deepcopy(state["binding"])
    state["binding"]["time_generation"] = record["next_time_generation"]
    state.update(revision=str(int(state["revision"]) + 1), status="unavailable",
                 current_anchor_ref=None,
                 invalidation_ref=object_ref(record, "invalidation_id", "invalidation_digest"))
    seal(state, "state_digest")
    return "closed_pending_fence"
