#!/usr/bin/env python3
"""Run the frozen complete branch-charge proof extension."""

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
    audit_branch_charge_certificate,
    audit_charge_certificate,
    generate_branch_charge_certificate,
    optimized_charge_certificate,
    write_branch_certificate,
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


def load_frozen_values(root: Path) -> dict[tuple[str, str], int]:
    values = {}
    path = root / "results" / "raw" / "main_runs.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == "factor_hybrid":
                values[(row["event"], row["budget_fraction"])] = int(row["value"])
    return values


def write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    protocol_path = root / "protocols" / "complete_certificate_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen":
        raise SystemExit("Refusing complete proof run: protocol is not frozen")
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    frozen = load_frozen_values(root)
    scale = int(protocol["certificate_scale"])
    node_limit = int(protocol["node_limit"])
    proof_dir = root / "results" / "complete_certificates"
    proof_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    for event in map(str, protocol["events"]):
        instance = load_instance(
            root / "data" / "instances" / f"event_{event}.json.gz"
        )
        for budget_value in protocol["budget_fractions"]:
            fraction = float(budget_value)
            fraction_key = f"{fraction:.4f}"
            budget = max(1, math.ceil(fraction * len(instance.candidates)))
            expected = frozen[(event, fraction_key)]
            bundle = bundle_greedy(instance, budget)

            root_charge = optimized_charge_certificate(
                instance, budget, bundle.selected, scale=scale
            )
            root_audit = audit_charge_certificate(instance, root_charge)
            milp_called = not root_audit.certified_optimal
            exact_runtime = 0.0
            if milp_called:
                exact = milp_exact(instance, budget)
                exact_runtime = exact.runtime_seconds
                if exact.value != expected:
                    raise AssertionError(
                        f"Frozen exact drift for {event}/{fraction_key}: "
                        f"{exact.value} != {expected}"
                    )
                selected = exact.selected
            else:
                if bundle.value != expected:
                    raise AssertionError(
                        f"Root charge closed a nonoptimal plan for "
                        f"{event}/{fraction_key}"
                    )
                selected = bundle.selected

            generation_started = time.perf_counter()
            proof = generate_branch_charge_certificate(
                instance,
                budget,
                selected,
                scale=scale,
                node_limit=node_limit,
            )
            generation_runtime = time.perf_counter() - generation_started
            verification_started = time.perf_counter()
            audit = audit_branch_charge_certificate(instance, proof)
            verification_runtime = time.perf_counter() - verification_started
            if audit.lower_value != expected:
                raise AssertionError(
                    f"Verified lower drift for {event}/{fraction_key}: "
                    f"{audit.lower_value} != {expected}"
                )

            if not milp_called:
                stage = "bundle_root"
            elif proof.root.kind == "bound":
                stage = "exact_root"
            else:
                stage = "branch_charge"
            proof_path = (
                proof_dir
                / f"{event}_b{int(round(10000 * fraction)):04d}.branch.json.gz"
            )
            write_branch_certificate(proof, proof_path)
            rows.append(
                {
                    "protocol_sha256": protocol_hash,
                    "event": event,
                    "budget_fraction": fraction_key,
                    "budget": budget,
                    "candidate_count": len(instance.candidates),
                    "bundle_value": bundle.value,
                    "frozen_exact_value": expected,
                    "bundle_root_certified": int(root_audit.certified_optimal),
                    "milp_called": int(milp_called),
                    "proof_stage": stage,
                    "verified_lower_value": audit.lower_value,
                    "proof_nodes": audit.nodes,
                    "proof_leaves": audit.leaves,
                    "maximum_depth": audit.maximum_depth,
                    "maximum_leaf_integer_upper": (
                        audit.maximum_leaf_integer_upper
                    ),
                    "generation_runtime_seconds": generation_runtime,
                    "verification_runtime_seconds": verification_runtime,
                    "milp_runtime_seconds": exact_runtime,
                    "proof_bytes": proof_path.stat().st_size,
                    "proof_file": str(proof_path.relative_to(root)),
                    "proof_sha256": sha256_file(proof_path),
                }
            )

    expected_pairs = int(
        protocol["completeness_gate"]["expected_event_budget_pairs"]
    )
    if len(rows) != expected_pairs:
        raise AssertionError(f"Expected {expected_pairs} proofs, got {len(rows)}")
    raw_path = root / "results" / "raw" / "complete_certificate_runs.csv"
    write_rows(raw_path, rows)

    stages = ("bundle_root", "exact_root", "branch_charge")
    stage_rows = [
        {
            "proof_stage": stage,
            "event_budget_pairs": sum(row["proof_stage"] == stage for row in rows),
            "total_nodes": sum(
                int(row["proof_nodes"]) for row in rows if row["proof_stage"] == stage
            ),
            "total_proof_bytes": sum(
                int(row["proof_bytes"]) for row in rows if row["proof_stage"] == stage
            ),
        }
        for stage in stages
    ]
    write_rows(root / "results" / "complete_certificate_summary.csv", stage_rows)
    payload = {
        "protocol_sha256": protocol_hash,
        "event_budget_pairs": len(rows),
        "all_exact_objectives_independently_verified": True,
        "bundle_root": sum(row["proof_stage"] == "bundle_root" for row in rows),
        "exact_root": sum(row["proof_stage"] == "exact_root" for row in rows),
        "branch_charge": sum(row["proof_stage"] == "branch_charge" for row in rows),
        "milp_calls": sum(int(row["milp_called"]) for row in rows),
        "total_nodes": sum(int(row["proof_nodes"]) for row in rows),
        "largest_proof_nodes": max(int(row["proof_nodes"]) for row in rows),
        "largest_proof_leaves": max(int(row["proof_leaves"]) for row in rows),
        "largest_proof_depth": max(int(row["maximum_depth"]) for row in rows),
        "total_compressed_bytes": sum(int(row["proof_bytes"]) for row in rows),
        "median_verification_runtime_seconds": statistics.median(
            float(row["verification_runtime_seconds"]) for row in rows
        ),
        "maximum_verification_runtime_seconds": max(
            float(row["verification_runtime_seconds"]) for row in rows
        ),
        "stages": stage_rows,
    }
    (root / "results" / "complete_certificate_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
