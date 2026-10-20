"""应用参考时钟候选格式唯一源；只生成设计资料。"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SID = "https://leafseamer.invalid/design/df03-reference/reference.schema.json"
VERSION = "reference-time/0.1.0-draft.1"


def obj(**fields):
    return dict(type="object", properties=fields, required=list(fields), additionalProperties=False)


def ref(name):
    return {"$ref": "#/$defs/" + name}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def array(schema, maximum=32):
    return dict(type="array", items=schema, maxItems=maximum, uniqueItems=True)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def build():
    d = {
        "Id": dict(type="string", minLength=1, maxLength=128,
                   pattern=r"^[A-Za-z0-9_.:-]+$(?![\s\S])"),
        "Digest": dict(type="string", pattern=r"^sha256:[0-9a-f]{64}$(?![\s\S])"),
        "UInt": dict(type="string", pattern=r"^(0|[1-9][0-9]{0,19})$(?![\s\S])"),
        "Positive": dict(type="string", pattern=r"^[1-9][0-9]{0,19}$(?![\s\S])"),
        "Signed": dict(type="string", pattern=r"^(0|-?[1-9][0-9]{0,29})$(?![\s\S])"),
        "Word": dict(type="string", pattern=r"^(0|[1-9][0-9]{0,9})$(?![\s\S])"),
    }
    d["Ref"] = obj(id=ref("Id"), revision=ref("Positive"), digest=ref("Digest"))
    d["Interval"] = obj(lower_ns=ref("Signed"), upper_ns=ref("Signed"))
    d["Stamp"] = obj(seconds=ref("Word"), fraction=ref("Word"), era=ref("Signed"))
    d["Domain"] = obj(authority_service_id=ref("Id"), database_instance_id=ref("Id"),
        provider_id=ref("Id"), provider_boot_id=ref("Id"), runtime_binding_ref=ref("Ref"),
        clock_domain_id=dict(type="string", pattern=r"^clock_[0-9a-f]{64}$(?![\s\S])"),
        descriptor_digest=ref("Digest"), clock_generation=ref("Positive"))
    d["Source"] = obj(source_id=ref("Id"), revision=ref("Positive"),
        configured_server_ref=ref("Ref"), endpoint_set_ref=ref("Ref"),
        effective_config_ref=ref("Ref"), authentication={"enum": ["nts", "trusted_network"]},
        trust_policy_ref=ref("Ref"), source_digest=ref("Digest"))
    d["Profile"] = obj(profile_id=ref("Id"), revision=ref("Positive"),
        model_id={"const": "reference-bound/1"}, model_revision={"const": "1"},
        collector_artifact_ref=ref("Ref"), protocol_artifact_ref=ref("Ref"),
        platform_qualification_ref=ref("Ref"), clock_method_ref=ref("Ref"),
        error_method_ref=ref("Ref"), era_method_ref=ref("Ref"),
        elapsed_model={"const": "observed-delta-relative/1"},
        elapsed_error_ppm=dict(type="integer", minimum=0, maximum=999999),
        span_quantization_ns=ref("UInt"),
        max_packet_bytes=dict(type="integer", minimum=48, maximum=65536),
        time_scale={"const": "posix-utc"}, leap_policy={"const": "normal-only"},
        smear_policy={"const": "forbidden"}, profile_digest=ref("Digest"))
    d["Policy"] = obj(policy_id=ref("Id"), revision=ref("Positive"),
        max_exchange_span_ns=ref("Positive"), max_exchange_age_ns=ref("Positive"),
        max_anchor_age_ns=ref("Positive"), max_upstream_age_ns=ref("Positive"),
        max_half_width_ns=ref("UInt"), policy_digest=ref("Digest"))
    d["Approval"] = obj(approval_id=ref("Id"), revision=ref("Positive"),
        profile_ref=ref("Ref"), source_ref=ref("Ref"),
        qualification_ref=ref("Ref"), authority_service_id=ref("Id"),
        status={"enum": ["approved", "revoked"]}, approval_digest=ref("Digest"))
    d["Binding"] = obj(domain=ref("Domain"), source_ref=ref("Ref"), profile_ref=ref("Ref"),
        approval_ref=ref("Ref"), policy_ref=ref("Ref"), time_generation=ref("Positive"))
    d["Request"] = obj(request_id=ref("Id"), revision=ref("Positive"), binding=ref("Binding"),
        correlation_ref=ref("Ref"), endpoint_ref=ref("Ref"),
        send_before_tick_ns=ref("UInt"), response_deadline_tick_ns=ref("Positive"),
        request_bytes_ref=ref("Ref"), request_size=dict(type="integer", minimum=48, maximum=65536),
        request_digest=ref("Digest"))
    d["AuthEvidence"] = obj(auth_id=ref("Id"), revision=ref("Positive"),
        request_ref=ref("Ref"), response_bytes_ref=ref("Ref"), source_ref=ref("Ref"),
        mode={"enum": ["nts", "trusted_network"]},
        verification_ref=ref("Ref"), bootstrap_ref=nullable(ref("Ref")),
        peer_binding_ref=ref("Ref"), authentication_digest=ref("Digest"))
    d["AuthEvidence"]["allOf"] = [{
        "if": {"properties": {"mode": {"const": "nts"}}},
        "then": {"properties": {"bootstrap_ref": ref("Ref")}},
        "else": {"properties": {"bootstrap_ref": {"type": "null"}}}
    }]
    d["ErrorEvidence"] = obj(error_id=ref("Id"), revision=ref("Positive"),
        binding=ref("Binding"), request_ref=ref("Ref"), response_bytes_ref=ref("Ref"),
        error_method_ref=ref("Ref"), qualification_ref=ref("Ref"),
        t2_error_ns=ref("UInt"), t3_error_ns=ref("UInt"),
        upstream_age_upper_at_m1_ns=ref("UInt"), provenance_ref=ref("Ref"),
        error_digest=ref("Digest"))
    d["EraEvidence"] = obj(era_id=ref("Id"), revision=ref("Positive"),
        request_ref=ref("Ref"), response_bytes_ref=ref("Ref"), method_ref=ref("Ref"),
        independent_time_ref=ref("Ref"), allowed_utc=ref("Interval"), era_digest=ref("Digest"))
    d["Exchange"] = obj(exchange_id=ref("Id"), revision=ref("Positive"),
        binding=ref("Binding"), request_ref=ref("Ref"), correlation_ref=ref("Ref"),
        endpoint_ref=ref("Ref"), response_bytes_ref=ref("Ref"),
        response_size=dict(type="integer", minimum=48, maximum=65536),
        receive_after_tick_ns=ref("UInt"),
        ntp_version=dict(type="integer", minimum=0, maximum=7),
        ntp_mode=dict(type="integer", minimum=0, maximum=7),
        leap=dict(type="integer", minimum=0, maximum=3),
        stratum=dict(type="integer", minimum=0, maximum=255),
        precision=dict(type="integer", minimum=-128, maximum=127),
        root_delay_word=ref("Word"), root_dispersion_word=ref("Word"),
        t2=ref("Stamp"), t3=ref("Stamp"),
        authentication_ref=ref("Ref"), error_ref=ref("Ref"), era_ref=ref("Ref"),
        parser_receipt_ref=ref("Ref"), exchange_digest=ref("Digest"))
    d["Anchor"] = obj(anchor_id=ref("Id"), revision={"const": "1"},
        model_id={"const": "reference-bound/1"}, model_revision={"const": "1"},
        binding=ref("Binding"), exchange_ref=ref("Ref"),
        anchor_tick_ns=ref("UInt"), exchange_start_tick_ns=ref("UInt"),
        utc_at_anchor=ref("Interval"), derivation_digest=ref("Digest"),
        anchor_digest=ref("Digest"))
    d["Assessment"] = obj(assessment_id=ref("Id"), revision={"const": "1"},
        model_id={"const": "reference-bound/1"}, model_revision={"const": "1"},
        binding=ref("Binding"), anchor_ref=ref("Ref"), assessed_tick_ns=ref("UInt"),
        utc=nullable(ref("Interval")), exchange_age_upper_ns=nullable(ref("UInt")),
        anchor_age_upper_ns=nullable(ref("UInt")), upstream_age_upper_ns=nullable(ref("UInt")),
        decision={"enum": ["conditional", "unavailable"]},
        reasons=array({"enum": ["binding", "approval", "runtime_clock", "source", "evidence",
            "expired", "uncertainty", "generation", "storage", "bootstrap", "invalid_interval"]}),
        assessment_digest=ref("Digest"))
    qualified = {n: ref(t) for n, t in (("utc", "Interval"), ("exchange_age_upper_ns", "UInt"),
        ("anchor_age_upper_ns", "UInt"), ("upstream_age_upper_ns", "UInt"))}
    d["Assessment"]["allOf"] = [{
        "if": {"properties": {"decision": {"const": "conditional"}}},
        "then": {"properties": {**qualified, "reasons": {"maxItems": 0}}},
        "else": {"properties": {**{n: {"type": "null"} for n in qualified},
                               "reasons": {"minItems": 1}}}
    }]
    d["Failure"] = obj(failure_id=ref("Id"), revision={"const": "1"}, domain=ref("Domain"),
        request_ref=nullable(ref("Ref")), observed_tick_ns=ref("UInt"),
        reason={"enum": ["timeout", "authentication", "kod", "packet", "source", "era",
            "leap", "smear", "upstream", "capacity", "storage", "runtime_clock", "revoked"]},
        diagnostic_ref=nullable(ref("Ref")), failure_digest=ref("Digest"))
    d["Invalidation"] = obj(invalidation_id=ref("Id"), revision={"const": "1"},
        old_binding=ref("Binding"), next_time_generation=ref("Positive"),
        cause_ref=ref("Ref"), deny_new_utc_permits={"const": True},
        protection_operation_ref=ref("Ref"), invalidation_digest=ref("Digest"))
    d["AuthorityState"] = obj(state_id=ref("Id"), revision=ref("Positive"),
        binding=ref("Binding"), status={"enum": ["cold", "collecting", "qualified", "unavailable"]},
        current_anchor_ref=nullable(ref("Ref")), invalidation_ref=nullable(ref("Ref")),
        state_digest=ref("Digest"))
    d["AuthorityState"]["allOf"] = [{
        "if": {"properties": {"status": {"const": "qualified"}}},
        "then": {"properties": {"current_anchor_ref": ref("Ref")}},
        "else": {"properties": {"current_anchor_ref": {"type": "null"}}}
    }, {
        "if": {"properties": {"status": {"const": "unavailable"}}},
        "then": {"properties": {"invalidation_ref": ref("Ref")}}
    }]
    d["Window"] = obj(not_before_utc_ns=ref("Signed"), not_after_utc_ns=ref("Signed"))
    d["UtcGuard"] = obj(guard_id=ref("Id"), revision={"const": "1"},
        model_id={"const": "reference-bound/1"}, model_revision={"const": "1"},
        binding=ref("Binding"), anchor_ref=ref("Ref"), assessment_ref=ref("Ref"),
        window=ref("Window"), expires_tick_ns=ref("Positive"), guard_digest=ref("Digest"))
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SID,
        "title": VERSION, "x-approved": False, "x-runtime-approved": False, "not": {}, "$defs": d}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = encoded(build())
    path = HERE / "reference.schema.json"
    if args.check:
        assert path.read_bytes() == content
    else:
        path.write_bytes(content)
