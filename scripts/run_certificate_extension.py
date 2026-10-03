#!/usr/bin/env python3
"""Run the frozen post-hoc charge-certificate extension."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

import yaml

from mirrorplan.algorithms import bundle_greedy, milp_exact
from mirrorplan.certificates import (
    audit_charge_certificate,
    equal_charge_certificate,
    optimized_charge_certificate,
    write_certificate,
)
from mirrorplan.instance import load_instance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_frozen_values(root: Path) -> dict[tuple[str, str, str], int]:
    path = root / "results" / "raw" / "main_runs.csv"
    values = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] in {"bundle_greedy", "factor_hybrid"}:
                values[(row["event"], row["budget_fraction"], row["method"])] = int(
                    row["value"]
                )
    return values


def main() -> None:
    args = parse_args()
    protocol_path = args.root / "protocols" / "certificate_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen":
        raise SystemExit("Refusing certificate run: protocol is not frozen")
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    frozen = load_frozen_values(args.root)
    scale = int(protocol["certificate_scale"])
    rows = []
    certificate_dir = args.root / "results" / "certificates"
    certificate_dir.mkdir(parents=True, exist_ok=True)

    for event in map(str, protocol["events"]):
        instance = load_instance(
            args.root / "data" / "instances" / f"event_{event}.json.gz"
        )
        for budget_value in protocol["budget_fractions"]:
            budget_fraction = float(budget_value)
            fraction_key = f"{budget_fraction:.4f}"
            budget = max(1, math.ceil(budget_fraction * len(instance.candidates)))

            bundle = bundle_greedy(instance, budget)
            expected_bundle = frozen[(event, fraction_key, "bundle_greedy")]
            expected_exact = frozen[(event, fraction_key, "factor_hybrid")]
            if bundle.value != expected_bundle:
                raise AssertionError(
                    f"Bundle drift for {event}/{fraction_key}: "
                    f"{bundle.value} != {expected_bundle}"
                )

            equal_started = time.perf_counter()
            equal_certificate = equal_charge_certificate(
                instance, budget, bundle.selected, scale=scale
            )
            equal_audit = audit_charge_certificate(instance, equal_certificate)
            equal_runtime = time.perf_counter() - equal_started

            optimized_started = time.perf_counter()
            optimized_certificate = optimized_charge_certificate(
                instance, budget, bundle.selected, scale=scale
            )
            optimized_audit = audit_charge_certificate(
                instance, optimized_certificate
            )
            optimized_runtime = time.perf_counter() - optimized_started
            if optimized_audit.upper_units > equal_audit.upper_units:
                raise AssertionError(
                    f"Optimized charge weaker than equal charge for "
                    f"{event}/{fraction_key}"
                )

            certificate_path = (
                certificate_dir
                / f"{event}_b{int(round(10000 * budget_fraction)):04d}.json.gz"
            )
            write_certificate(optimized_certificate, certificate_path)
            certificate_hash = sha256_file(certificate_path)

            escalated = not optimized_audit.certified_optimal
            escalated_value = ""
            escalation_runtime = 0.0
            if escalated:
                exact = milp_exact(instance, budget)
                escalated_value = exact.value
                escalation_runtime = exact.runtime_seconds
                if exact.value != expected_exact:
                    raise AssertionError(
                        f"Escalated MILP drift for {event}/{fraction_key}: "
                        f"{exact.value} != {expected_exact}"
                    )
            elif bundle.value != expected_exact:
                raise AssertionError(
                    f"Certificate incorrectly closed nonoptimal Bundle plan for "
                    f"{event}/{fraction_key}"
                )

            returned_value = (
                int(escalated_value) if escalated else bundle.value
            )
            if returned_value != expected_exact:
                raise AssertionError(
                    f"Certify-or-escalate returned {returned_value}, "
                    f"expected {expected_exact}"
                )
            rows.append(
                {
                    "protocol_sha256": protocol_hash,
                    "event": event,
                    "budget_fraction": fraction_key,
                    "budget": budget,
                    "candidate_count": len(instance.candidates),
                    "affected_targets": instance.affected_targets,
                    "bundle_value": bundle.value,
                    "frozen_exact_value": expected_exact,
                    "equal_upper_bound": equal_audit.upper_bound,
                    "equal_integer_upper_bound": equal_audit.integer_upper_bound,
                    "equal_certified_ratio": equal_audit.certified_ratio,
                    "optimized_upper_bound": optimized_audit.upper_bound,
                    "optimized_integer_upper_bound": (
                        optimized_audit.integer_upper_bound
                    ),
                    "optimized_certified_ratio": (
                        optimized_audit.certified_ratio
                    ),
                    "bundle_certified_optimal": int(
                        optimized_audit.certified_optimal
                    ),
                    "escalated_to_milp": int(escalated),
                    "escalated_value": escalated_value,
                    "returned_exact_value": returned_value,
                    "equal_certificate_runtime_seconds": equal_runtime,
                    "optimized_certificate_runtime_seconds": optimized_runtime,
                    "escalation_runtime_seconds": escalation_runtime,
                    "certificate_file": str(
                        certificate_path.relative_to(args.root)
                    ),
                    "certificate_sha256": certificate_hash,
                }
            )

    expected_pairs = int(
        protocol["completeness_gate"]["expected_event_budget_pairs"]
    )
    if len(rows) != expected_pairs:
        raise AssertionError(f"Expected {expected_pairs} rows, got {len(rows)}")

    raw_path = args.root / "results" / "raw" / "certificate_runs.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary_rows = []
    for budget_fraction in sorted({row["budget_fraction"] for row in rows}):
        subset = [row for row in rows if row["budget_fraction"] == budget_fraction]
        ratios = [float(row["optimized_certified_ratio"]) for row in subset]
        summary_rows.append(
            {
                "budget_fraction": budget_fraction,
                "event_budget_pairs": len(subset),
                "mean_certified_ratio": statistics.mean(ratios),
                "median_certified_ratio": statistics.median(ratios),
                "minimum_certified_ratio": min(ratios),
                "bundle_certified_optimal": sum(
                    int(row["bundle_certified_optimal"]) for row in subset
                ),
                "bundle_actually_optimal": sum(
                    int(row["bundle_value"] == row["frozen_exact_value"])
                    for row in subset
                ),
                "escalated_to_milp": sum(
                    int(row["escalated_to_milp"]) for row in subset
                ),
                "median_certificate_runtime_seconds": statistics.median(
                    float(row["optimized_certificate_runtime_seconds"])
                    for row in subset
                ),
            }
        )
    summary_path = args.root / "results" / "certificate_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    all_ratios = [float(row["optimized_certified_ratio"]) for row in rows]
    payload = {
        "protocol_sha256": protocol_hash,
        "event_budget_pairs": len(rows),
        "mean_certified_ratio": statistics.mean(all_ratios),
        "median_certified_ratio": statistics.median(all_ratios),
        "minimum_certified_ratio": min(all_ratios),
        "bundle_certified_optimal": sum(
            int(row["bundle_certified_optimal"]) for row in rows
        ),
        "bundle_actually_optimal": sum(
            int(row["bundle_value"] == row["frozen_exact_value"])
            for row in rows
        ),
        "escalated_to_milp": sum(int(row["escalated_to_milp"]) for row in rows),
        "escalated_values_match": all(
            not int(row["escalated_to_milp"])
            or int(row["escalated_value"]) == int(row["frozen_exact_value"])
            for row in rows
        ),
        "by_budget": summary_rows,
    }
    (args.root / "results" / "certificate_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
