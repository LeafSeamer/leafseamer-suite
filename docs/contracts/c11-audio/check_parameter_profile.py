"""校验随仓交付的DM3参数候选；仅离线数据检查，不授予设备运行资格。"""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUTS = ("dm3-parameter-profile.json", "dm3-legacy-catalog.json",
          "check_parameter_profile.py")
PROFILE_KEYS = {"format_version", "profile_id", "protocol_family", "model_family",
                "status", "runtime_approved", "entry_count", "entries"}
ENTRY_KEYS = {"index", "address", "x_count", "y_count", "min", "max",
              "default_lexeme", "unit", "value_type", "qualifier", "access", "scale"}
INTEGER_KEYS = ("index", "x_count", "y_count", "min", "max", "scale")


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def errors(profile):
    """接受集仅覆盖本候选文件；不解释设备报文或认证上下文。"""
    if not isinstance(profile, dict) or set(profile) != PROFILE_KEYS:
        return {"profile_shape"}
    found = set()
    fixed = {
        "format_version": "dm3-parameter-profile/1",
        "profile_id": "dm3-rcp-parameters-candidate-1",
        "protocol_family": "yamaha_rcp", "model_family": "DM3",
        "status": "candidate_only",
    }
    if any(profile[k] != v for k, v in fixed.items()):
        found.add("profile_identity")
    if profile["runtime_approved"] is not False:
        found.add("runtime_approval")
    entries = profile["entries"]
    if not isinstance(entries, list) or not entries or len(entries) > 1024:
        return found | {"entries"}
    if type(profile["entry_count"]) is not int or profile["entry_count"] != len(entries):
        found.add("entry_count")
    indices, addresses = [], []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            found.add("entry_shape")
            continue
        if any(type(entry[k]) is not int or abs(entry[k]) > 2**53 - 1 for k in INTEGER_KEYS):
            found.add("integer")
            continue
        indices.append(entry["index"])
        if not isinstance(entry["address"], str) or not entry["address"].startswith(("MIXER:", "IO:")):
            found.add("address")
        elif any(c.isspace() or ord(c) < 32 for c in entry["address"]):
            found.add("address")
        else:
            addresses.append(entry["address"])
        if entry["x_count"] < 1 or entry["y_count"] < 1 or entry["scale"] < 1:
            found.add("dimensions")
        if entry["min"] > entry["max"]:
            found.add("range")
        if entry["access"] not in ("r", "rw"):
            found.add("access")
        if entry["value_type"] not in ("integer", "binary", "string"):
            found.add("value_type")
        if entry["qualifier"] != "any":
            found.add("qualifier")
        if any(not isinstance(entry[k], str) or "\n" in entry[k] or "\r" in entry[k]
               for k in ("unit", "default_lexeme")):
            found.add("text")
    if indices != list(range(len(entries))):
        found.add("indices")
    if len(set(addresses)) != len(addresses):
        found.add("duplicate_address")
    return found


def compatibility(profile, legacy):
    current = {e["address"]: e for e in profile["entries"]}
    previous = {e["address"]: e for e in legacy["entries"] if e["action"] == "prminfo"}
    shared = current.keys() & previous.keys()
    fields = sorted(ENTRY_KEYS - {"index", "address"})
    changes = []
    for address in sorted(shared):
        for field in fields:
            if current[address][field] != previous[address][field]:
                changes.append({"address": address, "field": field,
                                "legacy": previous[address][field],
                                "candidate": current[address][field]})
    return {
        "parameter_count": len(current),
        "legacy_parameter_count": len(previous),
        "shared_address_count": len(shared),
        "changed_index_count": sum(current[a]["index"] != previous[a]["index"] for a in shared),
        "access_counts": dict(sorted(Counter(e["access"] for e in current.values()).items())),
        "added_addresses": sorted(current.keys() - previous.keys()),
        "removed_addresses": sorted(previous.keys() - current.keys()),
        "definition_changes": changes,
    }


def run():
    profile = load(INPUTS[0])
    assert not errors(profile), errors(profile)
    # 手写预期覆盖身份误用、运行批准、字段扩张、类型及目录完整性。
    cases = [
        ("P01", ["status"], "qualified", "profile_identity"),
        ("P02", ["runtime_approved"], True, "runtime_approval"),
        ("P03", ["runtime_approved"], 0, "runtime_approval"),
        ("P04", ["entry_count"], 176, "entry_count"),
        ("P05", ["entry_count"], True, "entry_count"),
        ("P06", ["entries"], [], "entries"),
        ("P07", ["entries", 1, "index"], 0, "indices"),
        ("P08", ["entries", 0, "index"], True, "integer"),
        ("P09", ["entries", 0, "max"], 2**53, "integer"),
        ("P10", ["entries", 0, "max"], -32769, "range"),
        ("P11", ["entries", 0, "x_count"], 0, "dimensions"),
        ("P12", ["entries", 0, "scale"], 0, "dimensions"),
        ("P13", ["entries", 0, "access"], "w", "access"),
        ("P14", ["entries", 0, "value_type"], "boolean", "value_type"),
        ("P15", ["entries", 0, "qualifier"], "unknown", "qualifier"),
        ("P16", ["entries", 0, "default_lexeme"], 0, "text"),
        ("P17", ["entries", 0, "unit"], "dB\n", "text"),
        ("P18", ["entries", 0, "address"], "other:Level", "address"),
        ("P19", ["entries", 1, "address"], profile["entries"][0]["address"], "duplicate_address"),
        ("P20", ["extra"], "unapproved", "profile_shape"),
        ("P21", ["entries", 0, "extra"], "unapproved", "entry_shape"),
        ("P22", ["protocol_family"], "yamaha_osc", "profile_identity"),
    ]
    results = [{"id": "P00", "passed": True, "expected": "valid"}]
    for name, path, value, expected in cases:
        candidate = copy.deepcopy(profile)
        target = candidate
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        actual = errors(candidate)
        assert expected in actual, (name, expected, actual)
        results.append({"id": name, "passed": True, "expected": expected})
    comparison = compatibility(profile, load(INPUTS[1]))
    expected = {
        "parameter_count": 177, "legacy_parameter_count": 174,
        "shared_address_count": 174, "changed_index_count": 154,
        "access_counts": {"r": 16, "rw": 161},
        "added_addresses": ["IO:Current/PortToPort/48VOn",
                            "IO:Current/PortToPort/HAAvailability",
                            "IO:Current/PortToPort/HAGain"],
        "removed_addresses": [],
        "definition_changes": [{
            "address": "MIXER:Current/MuteGrpCtrl/On",
            "field": "access", "legacy": "rw", "candidate": "r",
        }],
    }
    assert comparison == expected, comparison
    results.append({"id": "P23", "passed": True, "expected": "fixed_compatibility"})
    return {
        "format_version": "dm3-parameter-profile-check/1",
        "runtime_approved": False, "device_tests_executed": 0,
        "all_passed": True, "checks_passed": len(results),
        "results": results, "compatibility": comparison,
        "artifact_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                            for name in INPUTS},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    report = run()
    if args.report:
        (ROOT / "parameter-profile-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    print(json.dumps({k: report[k] for k in (
        "all_passed", "checks_passed", "device_tests_executed", "compatibility"
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
