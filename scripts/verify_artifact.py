#!/usr/bin/env python3
"""Verify a packaged MirrorPlan artifact using only the standard library."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


PINNED_COMMIT = "0e719b8587e30f464f2e204127e844833efbe965"
FORBIDDEN_PARTS = {
    ("data", "raw"),
    ("data", "instances"),
}
FORBIDDEN_NAMES = {"main_selections.jsonl"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_manifest(root: Path) -> list[Path]:
    manifest = root / "MANIFEST.sha256"
    if not manifest.exists():
        raise SystemExit("Missing MANIFEST.sha256; verify the packaged directory")
    listed: list[Path] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise SystemExit(f"Unsafe manifest path: {relative}")
        if not path.is_file():
            raise SystemExit(f"Manifest file missing: {relative}")
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(
                f"Manifest mismatch for {relative}: expected {expected}, got {actual}"
            )
        listed.append(path)
    return listed


def verify_packaging_boundary(root: Path, listed: list[Path]) -> None:
    private_markers = {str(Path.home()).encode()}
    for forbidden in FORBIDDEN_PARTS:
        directory = root.joinpath(*forbidden)
        if directory.exists() and any(path.is_file() for path in directory.rglob("*")):
            raise SystemExit(f"Forbidden upstream-derived directory packaged: {directory}")
    if any(path.name in FORBIDDEN_NAMES for path in root.rglob("*")):
        raise SystemExit("Repository-level selections are present outside the manifest")
    for path in listed:
        relative = path.relative_to(root)
        parts = relative.parts
        if any(parts[:2] == forbidden for forbidden in FORBIDDEN_PARTS):
            raise SystemExit(f"Forbidden upstream-derived path packaged: {relative}")
        if path.name in FORBIDDEN_NAMES:
            raise SystemExit(f"Repository-level selections packaged: {relative}")
        payload = path.read_bytes()
        if any(marker in payload for marker in private_markers):
            raise SystemExit(f"Private local path marker found in {relative}")


def verify_sources(root: Path) -> None:
    source_rows = json.loads(
        (root / "data" / "source_manifest.json").read_text(encoding="utf-8")
    )
    if len(source_rows) != 32:
        raise SystemExit(f"Expected 32 pinned source records, found {len(source_rows)}")
    if len({row["relative_path"] for row in source_rows}) != 32 or len(
        {row["url"] for row in source_rows}
    ) != 32:
        raise SystemExit("Pinned source records contain duplicate paths or URLs")
    for row in source_rows:
        relative = Path(row["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"Unsafe source path: {relative}")
        if PINNED_COMMIT not in row["url"]:
            raise SystemExit(f"Unpinned source URL: {row['url']}")
        if len(row["sha256"]) != 64 or int(row["bytes"]) <= 0:
            raise SystemExit(f"Invalid source record: {row}")


def verify_registered_rows(root: Path) -> None:
    protocol_path = root / "protocols" / "main.yaml"
    protocol_hash = sha256(protocol_path)
    environment = json.loads(
        (root / "results" / "raw" / "environment.json").read_text(encoding="utf-8")
    )
    if environment["protocol_sha256"] != protocol_hash:
        raise SystemExit("Frozen protocol hash disagrees with registered environment")

    main_rows = rows(root / "results" / "raw" / "main_runs.csv")
    if len(main_rows) != 4400:
        raise SystemExit(f"Expected 4400 main rows, found {len(main_rows)}")
    if {row["protocol_sha256"] for row in main_rows} != {protocol_hash}:
        raise SystemExit("Main rows contain an unexpected protocol hash")
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in main_rows:
        grouped[(row["event"], row["budget_fraction"])].append(row)
    if len(grouped) != 80:
        raise SystemExit(f"Expected 80 event-budget groups, found {len(grouped)}")
    deterministic = {
        "factor_hybrid",
        "milp_exact",
        "bundle_greedy",
        "peeling",
        "impact",
    }
    for key, group in grouped.items():
        methods = [row["method"] for row in group]
        if any(methods.count(method) != 1 for method in deterministic):
            raise SystemExit(f"Incomplete deterministic methods for {key}")
        random_rows = [row for row in group if row["method"] == "random"]
        if {int(row["seed"]) for row in random_rows} != set(range(50)):
            raise SystemExit(f"Incomplete random seeds for {key}")
        values = {
            row["method"]: int(row["value"])
            for row in group
            if row["method"] in deterministic
        }
        if values["factor_hybrid"] != values["milp_exact"]:
            raise SystemExit(f"Exact solvers disagree for {key}")

    alert_rows = rows(root / "results" / "raw" / "alert_recall_runs.csv")
    if len(alert_rows) != 6400:
        raise SystemExit(f"Expected 6400 alert rows, found {len(alert_rows)}")
    alert_groups: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in alert_rows:
        alert_groups[(row["event"], row["alert_recall"])].add(int(row["seed"]))
    if len(alert_groups) != 64 or any(
        seeds != set(range(100)) for seeds in alert_groups.values()
    ):
        raise SystemExit("Alert-recall event, level, or seed coverage is incomplete")

    runtime_rows = rows(root / "results" / "raw" / "runtime_runs.csv")
    if len(runtime_rows) != 1120:
        raise SystemExit(f"Expected 1120 runtime rows, found {len(runtime_rows)}")
    runtime_groups: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for row in runtime_rows:
        runtime_groups[(row["event"], row["budget_fraction"], row["method"])].add(
            int(row["repetition"])
        )
    if len(runtime_groups) != 160 or any(
        repetitions != set(range(7)) for repetitions in runtime_groups.values()
    ):
        raise SystemExit("Runtime event, budget, method, or repetition coverage is incomplete")

    oracle_rows = rows(root / "results" / "oracle_checks.csv")
    if len(oracle_rows) != 80 or any(row["agree"] != "1" for row in oracle_rows):
        raise SystemExit("The packaged oracle audit is incomplete or contains disagreement")

    core_protocol = root / "protocols" / "core_extension.yaml"
    core_hash = sha256(core_protocol)
    core_rows = rows(root / "results" / "raw" / "core_extension_runs.csv")
    if len(core_rows) != 1680:
        raise SystemExit(f"Expected 1680 core rows, found {len(core_rows)}")
    if {row["protocol_sha256"] for row in core_rows} != {core_hash}:
        raise SystemExit("Core rows contain an unexpected protocol hash")
    core_groups: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    core_values: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in core_rows:
        core_groups[(row["event"], row["budget_fraction"], row["method"])].add(
            int(row["repetition"])
        )
        core_values[(row["event"], row["budget_fraction"])].add(int(row["value"]))
    if len(core_groups) != 240 or any(
        repetitions != set(range(7)) for repetitions in core_groups.values()
    ):
        raise SystemExit("Core extension method or repetition coverage is incomplete")
    if len(core_values) != 80 or any(len(values) != 1 for values in core_values.values()):
        raise SystemExit("Core extension exact methods disagree")

    stress_protocol = root / "protocols" / "alert_stress.yaml"
    stress_hash = sha256(stress_protocol)
    stress_rows = rows(root / "results" / "raw" / "alert_stress_runs.csv")
    if len(stress_rows) != 12864:
        raise SystemExit(f"Expected 12864 alert-stress rows, found {len(stress_rows)}")
    if {row["protocol_sha256"] for row in stress_rows} != {stress_hash}:
        raise SystemExit("Alert-stress rows contain an unexpected protocol hash")
    stress_groups: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for row in stress_rows:
        key = (row["event"], row["mechanism"], row["alert_recall"])
        stress_groups[key].add(int(row["seed"]))
        expected_alerts = round(
            float(row["alert_recall"]) * int(row["original_candidates"])
        )
        if int(row["alerted_candidates"]) != expected_alerts:
            raise SystemExit(f"Alert count disagrees with recall for {key}")
    if len(stress_groups) != 192:
        raise SystemExit("Alert-stress event, mechanism, or recall coverage is incomplete")
    for (_, mechanism, _), seeds in stress_groups.items():
        expected_seeds = {0} if mechanism == "impact_targeted" else set(range(100))
        if seeds != expected_seeds:
            raise SystemExit(f"Alert-stress seed coverage is incomplete for {mechanism}")

    mechanism_protocol = root / "protocols" / "mechanism_extension.yaml"
    mechanism_hash = sha256(mechanism_protocol)
    mechanism_rows = rows(root / "results" / "mechanism_runs.csv")
    if len(mechanism_rows) != 80:
        raise SystemExit(f"Expected 80 mechanism rows, found {len(mechanism_rows)}")
    if {row["protocol_sha256"] for row in mechanism_rows} != {mechanism_hash}:
        raise SystemExit("Mechanism rows contain an unexpected protocol hash")
    if any(
        int(row["exact_value"]) < int(row["additive_value"])
        for row in mechanism_rows
    ):
        raise SystemExit("An additive-ablation value exceeds the certified optimum")

    certificate_protocol = root / "protocols" / "certificate_extension.yaml"
    certificate_hash = sha256(certificate_protocol)
    certificate_rows = rows(
        root / "results" / "raw" / "certificate_runs.csv"
    )
    if len(certificate_rows) != 80:
        raise SystemExit(
            f"Expected 80 root certificate rows, found {len(certificate_rows)}"
        )
    if {
        row["protocol_sha256"] for row in certificate_rows
    } != {certificate_hash}:
        raise SystemExit("Root certificate rows have an unexpected protocol hash")
    if sum(
        int(row["bundle_certified_optimal"]) for row in certificate_rows
    ) != 76 or sum(
        int(row["escalated_to_milp"]) for row in certificate_rows
    ) != 4:
        raise SystemExit("Root certificate closure counts disagree")
    for row in certificate_rows:
        certificate = (root / row["certificate_file"]).resolve()
        if not certificate.is_relative_to(root) or not certificate.is_file():
            raise SystemExit(f"Missing root certificate: {certificate}")
        if sha256(certificate) != row["certificate_sha256"]:
            raise SystemExit(f"Root certificate hash mismatch: {certificate}")

    gap_protocol = root / "protocols" / "gap_extension.yaml"
    gap_hash = sha256(gap_protocol)
    gap_rows = rows(root / "results" / "raw" / "gap_extension_runs.csv")
    if len(gap_rows) != 64320:
        raise SystemExit(f"Expected 64320 gap rows, found {len(gap_rows)}")
    if {row["protocol_sha256"] for row in gap_rows} != {gap_hash}:
        raise SystemExit("Gap rows contain an unexpected protocol hash")
    gap_keys = set()
    for row in gap_rows:
        key = (
            row["event"],
            row["mechanism"],
            row["alert_recall"],
            row["seed"],
            row["budget_fraction"],
        )
        if key in gap_keys:
            raise SystemExit(f"Duplicate gap row: {key}")
        gap_keys.add(key)
        if int(row["exact_value"]) < int(row["bundle_value"]):
            raise SystemExit(f"Exact is below Bundle for gap row {key}")
        total = int(row["all_affected_targets"])
        decomposition = sum(
            int(row[column])
            for column in (
                "recovered_value",
                "allocation_gap",
                "capacity_gap",
                "alert_gap",
            )
        )
        if decomposition != total:
            raise SystemExit(f"Gap identity failed for {key}")

    complete_protocol = (
        root / "protocols" / "complete_certificate_extension.yaml"
    )
    complete_hash = sha256(complete_protocol)
    complete_rows = rows(
        root / "results" / "raw" / "complete_certificate_runs.csv"
    )
    if len(complete_rows) != 80:
        raise SystemExit(
            f"Expected 80 complete proof rows, found {len(complete_rows)}"
        )
    if {
        row["protocol_sha256"] for row in complete_rows
    } != {complete_hash}:
        raise SystemExit("Complete proof rows have an unexpected protocol hash")
    stages = {
        stage: sum(row["proof_stage"] == stage for row in complete_rows)
        for stage in ("bundle_root", "exact_root", "branch_charge")
    }
    if stages != {"bundle_root": 76, "exact_root": 2, "branch_charge": 2}:
        raise SystemExit(f"Complete proof closure counts disagree: {stages}")
    for row in complete_rows:
        if int(row["verified_lower_value"]) != int(row["frozen_exact_value"]):
            raise SystemExit("Complete proof lower differs from frozen exact")
        if int(row["maximum_leaf_integer_upper"]) > int(
            row["verified_lower_value"]
        ):
            raise SystemExit("Complete proof contains an unclosed leaf")
        proof = (root / row["proof_file"]).resolve()
        if not proof.is_relative_to(root) or not proof.is_file():
            raise SystemExit(f"Missing complete proof: {proof}")
        if sha256(proof) != row["proof_sha256"]:
            raise SystemExit(f"Complete proof hash mismatch: {proof}")
        if proof.stat().st_size != int(row["proof_bytes"]):
            raise SystemExit(f"Complete proof size mismatch: {proof}")


def verify_fse_revision(root: Path) -> dict:
    if not (root / "protocols/fse_revision.yaml").exists():
        return {}
    retained = {
        (row["event"], row["budget_fraction"], row["method"]): int(row["value"])
        for row in rows(root / "results/raw/main_runs.csv")
        if row["method"] != "random"
    }
    timings = rows(root / "results/raw/fse_decision_runtime.csv")
    loads = rows(root / "results/raw/fse_instance_load_runtime.csv")
    if len(timings) != 1680 or len(loads) != 112:
        raise SystemExit("FSE revision row counts are incomplete")
    grouped = defaultdict(list)
    seen = set()
    stage_counts = defaultdict(int)
    expected_methods = {"bundle_greedy", "milp_exact", "certify_or_escalate"}
    for row in timings:
        key = (row["event"], row["budget_fraction"], row["method"])
        unique = (*key, int(row["repetition"]))
        if unique in seen or row["method"] not in expected_methods:
            raise SystemExit("Invalid or duplicate FSE timing row")
        seen.add(unique)
        elapsed = float(row["decision_seconds"])
        phases = json.loads(row["phase_seconds"])
        if not math.isfinite(elapsed) or elapsed <= 0 or any(
            not math.isfinite(value) or value < 0 for value in phases.values()
        ) or sum(phases.values()) > elapsed:
            raise SystemExit("Invalid FSE decision timing boundary")
        method = "bundle_greedy" if row["method"] == "bundle_greedy" else "factor_hybrid"
        if int(row["value"]) != retained[(key[0], key[1], method)]:
            raise SystemExit("FSE revision changed a frozen objective")
        if int(row["exact_value"]) != retained[(key[0], key[1], "factor_hybrid")]:
            raise SystemExit("FSE revision reference value is incorrect")
        if row["method"] == "certify_or_escalate":
            stage_counts[row["proof_stage"]] += 1
        grouped[key].append(elapsed)
    if len(grouped) != 240 or any(
        {int(r) for e, q, m, r in seen if (e, q, m) == key} != set(range(7))
        for key in grouped
    ):
        raise SystemExit("FSE method or repetition coverage is incomplete")
    if dict(stage_counts) != {"bundle_root": 532, "exact_root": 14, "branch_charge": 14}:
        raise SystemExit("FSE proof stages differ from the retained cascade")
    load_keys = {(r["event"], int(r["repetition"])) for r in loads}
    events = {key[0] for key in grouped}
    if load_keys != {(event, repetition) for event in events for repetition in range(7)}:
        raise SystemExit("FSE loading coverage is incomplete")
    if any(not math.isfinite(float(r["load_seconds"])) or float(r["load_seconds"]) <= 0 for r in loads):
        raise SystemExit("Invalid FSE load timing")
    for summary in rows(root / "results/fse_decision_runtime_summary.csv"):
        values = [statistics.median(v) * 1000 for (e, q, m), v in grouped.items()
                  if m == summary["method"]]
        if int(summary["pairs"]) != 80 or not math.isclose(
            statistics.median(values), float(summary["median_ms"]), rel_tol=1e-12
        ) or not math.isclose(max(values), float(summary["maximum_ms"]), rel_tol=1e-12):
            raise SystemExit("FSE timing summary disagrees with raw measurements")
    cases = rows(root / "results/fse_escalation_cases.csv")
    if {(r["event"], r["budget_fraction"]) for r in cases} != {
        ("0409", "0.0500"), ("0507", "0.1000"),
        ("0507", "0.2000"), ("0514", "0.0500")
    }:
        raise SystemExit("FSE escalation cases are incomplete")
    for row in cases:
        if int(row["gained_target_weight"]) - int(row["lost_target_weight"]) != (
            int(row["exact_value"]) - int(row["bundle_value"])
        ):
            raise SystemExit("FSE case changes do not explain the objective difference")
    return {"fse_decision_rows": len(timings), "fse_load_rows": len(loads),
            "fse_escalations": len(cases)}


def verify_matched_certification(root: Path) -> dict:
    path = root / "results/raw/matched_certification_runtime.csv"
    if not path.exists():
        return {}
    timings = rows(path)
    retained = {(r["event"], r["budget_fraction"], r["method"]): int(r["value"])
                for r in rows(root / "results/raw/main_runs.csv") if r["method"] != "random"}
    methods = {"bundle_greedy", "milp_exact", "certify_or_escalate", "milp_then_certify"}
    certified = {"certify_or_escalate", "milp_then_certify"}
    seen, grouped = set(), defaultdict(list)
    for row in timings:
        key = (row["event"], row["budget_fraction"], row["method"])
        unique = (*key, int(row["repetition"]))
        elapsed, phases = float(row["decision_seconds"]), json.loads(row["phase_seconds"])
        if unique in seen or key[2] not in methods or not math.isfinite(elapsed) or elapsed <= 0:
            raise SystemExit("Invalid matched-certification timing row")
        if any(not math.isfinite(v) or v < 0 for v in phases.values()) or sum(phases.values()) > elapsed:
            raise SystemExit("Invalid matched-certification timing boundary")
        seen.add(unique)
        reference = "bundle_greedy" if key[2] == "bundle_greedy" else "factor_hybrid"
        if int(row["value"]) != retained[(key[0], key[1], reference)] or int(row["exact_value"]) != retained[(key[0], key[1], "factor_hybrid")]:
            raise SystemExit("Matched-certification objective changed")
        if int(row["certified_optimal"]) != int(key[2] in certified):
            raise SystemExit("Matched-certification proof status is incorrect")
        if key[2] in certified and (int(row["proof_nodes"]) not in {1, 3} or int(row["proof_depth"]) not in {0, 1}):
            raise SystemExit("Unexpected matched proof structure")
        grouped[key].append(row)
    events = {e for e, q, m in retained}
    quotas = {q for e, q, m in retained}
    if seen != {(e, q, m, r) for e in events for q in quotas for m in methods for r in range(7)} or len(timings) != 2240:
        raise SystemExit("Matched-certification coverage is incomplete")
    for summary in rows(root / "results/matched_certification_runtime_summary.csv"):
        values = [statistics.median(float(r["decision_seconds"]) for r in group) * 1000
                  for (e, q, m), group in grouped.items() if m == summary["method"]]
        if int(summary["pairs"]) != 80 or not math.isclose(statistics.median(values), float(summary["median_ms"]), rel_tol=1e-12) or not math.isclose(max(values), float(summary["maximum_ms"]), rel_tol=1e-12):
            raise SystemExit("Matched-certification summary disagrees with measurements")
    return {"matched_certification_rows": len(timings), "matched_certification_pairs": 80}


def main() -> None:
    root = parse_args().root.resolve()
    listed = verify_manifest(root)
    verify_packaging_boundary(root, listed)
    verify_sources(root)
    verify_registered_rows(root)
    fse_report = verify_fse_revision(root)
    matched_report = verify_matched_certification(root)
    print(
        json.dumps(
            {
                "status": "passed",
                "manifest_files": len(listed),
                "source_records": 32,
                "main_rows": 4400,
                "alert_rows": 6400,
                "runtime_rows": 1120,
                "oracle_agreements": 80,
                "core_rows": 1680,
                "alert_stress_rows": 12864,
                "mechanism_rows": 80,
                "root_certificate_rows": 80,
                "gap_rows": 64320,
                "complete_proofs": 80,
                **fse_report,
                **matched_report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
