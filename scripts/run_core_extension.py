#!/usr/bin/env python3
"""Run the frozen complementarity-core algorithmic extension."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

from mirrorplan.algorithms import core_factor_hybrid, factor_hybrid, milp_exact
from mirrorplan.instance import (
    complementarity_core,
    interaction_components,
    load_instance,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    protocol_path = args.root / "protocols" / "core_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen":
        raise SystemExit("Refusing extension run: protocol status is not frozen")
    protocol_hash = sha256(protocol_path)
    component_limit = int(protocol["component_enumeration_limit"])
    methods = {
        "core_factor": lambda instance, budget: core_factor_hybrid(
            instance, budget, component_limit
        ),
        "factor_hybrid": lambda instance, budget: factor_hybrid(
            instance, budget, component_limit
        ),
        "milp_exact": milp_exact,
    }
    method_names = list(protocol["methods"])
    warmups = int(protocol["runtime"]["warmups"])
    repetitions = int(protocol["runtime"]["measured_repetitions"])
    run_rows: list[dict] = []
    structure_rows: list[dict] = []

    for event_index, event in enumerate(map(str, protocol["events"])):
        instance = load_instance(
            args.root / "data" / "instances" / f"event_{event}.json.gz"
        )
        core = complementarity_core(instance)
        core_components = [
            component
            for component in interaction_components(instance)
            if component.intersection(core)
        ]
        structure_rows.append(
            {
                "event": event,
                "candidates": len(instance.candidates),
                "core_candidates": len(core),
                "core_fraction": len(core) / len(instance.candidates),
                "singleton_tail_candidates": len(instance.candidates) - len(core),
                "core_components": len(core_components),
                "max_core_component": max(map(len, core_components), default=0),
            }
        )
        for budget_index, fraction_value in enumerate(protocol["budget_fractions"]):
            fraction = float(fraction_value)
            budget = min(
                len(instance.candidates),
                max(1, math.ceil(fraction * len(instance.candidates))),
            )
            for _ in range(warmups):
                for method in method_names:
                    methods[method](instance, budget)

            pair_values: dict[str, set[int]] = defaultdict(set)
            for repetition in range(repetitions):
                offset = (event_index + budget_index + repetition) % len(method_names)
                ordered = method_names[offset:] + method_names[:offset]
                for order, method in enumerate(ordered):
                    solution = methods[method](instance, budget)
                    pair_values[method].add(solution.value)
                    run_rows.append(
                        {
                            "protocol_sha256": protocol_hash,
                            "event": event,
                            "budget_fraction": f"{fraction:.4f}",
                            "budget": budget,
                            "method": method,
                            "repetition": repetition,
                            "invocation_order": order,
                            "value": solution.value,
                            "runtime_seconds": solution.runtime_seconds,
                        }
                    )
            observed = {value for values in pair_values.values() for value in values}
            if len(observed) != 1 or any(len(values) != 1 for values in pair_values.values()):
                raise SystemExit(
                    f"Exact-method disagreement for event={event}, budget={budget}: "
                    f"{dict(pair_values)}"
                )

    raw_path = args.root / "results" / "raw" / "core_extension_runs.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(run_rows[0]))
        writer.writeheader()
        writer.writerows(run_rows)

    structure_path = args.root / "results" / "core_structure.csv"
    with structure_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(structure_rows[0]))
        writer.writeheader()
        writer.writerows(structure_rows)

    measurements: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in run_rows:
        measurements[(row["event"], row["budget_fraction"], row["method"])].append(
            float(row["runtime_seconds"])
        )
    runtime_rows = []
    for method in method_names:
        pair_medians = [
            statistics.median(values)
            for (_, _, row_method), values in measurements.items()
            if row_method == method
        ]
        runtime_rows.append(
            {
                "method": method,
                "event_budget_pairs": len(pair_medians),
                "repetitions_per_pair": repetitions,
                "median_pair_runtime_seconds": statistics.median(pair_medians),
                "p95_pair_runtime_seconds": float(np.percentile(pair_medians, 95)),
                "max_pair_runtime_seconds": max(pair_medians),
                "sum_pair_medians_seconds": sum(pair_medians),
            }
        )
    runtime_path = args.root / "results" / "core_runtime_summary.csv"
    with runtime_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(runtime_rows[0]))
        writer.writeheader()
        writer.writerows(runtime_rows)

    total_candidates = sum(int(row["candidates"]) for row in structure_rows)
    total_core = sum(int(row["core_candidates"]) for row in structure_rows)
    payload = {
        "protocol_sha256": protocol_hash,
        "events": len(structure_rows),
        "event_budget_pairs": len(protocol["events"])
        * len(protocol["budget_fractions"]),
        "runtime_rows": len(run_rows),
        "all_objectives_agree": True,
        "total_candidates": total_candidates,
        "total_core_candidates": total_core,
        "core_candidate_fraction": total_core / total_candidates,
        "events_with_empty_core": sum(
            int(row["core_candidates"]) == 0 for row in structure_rows
        ),
        "events_with_core_at_most_39": sum(
            int(row["core_candidates"]) <= 39 for row in structure_rows
        ),
        "largest_core_candidates": max(
            int(row["core_candidates"]) for row in structure_rows
        ),
        "largest_core_component": max(
            int(row["max_core_component"]) for row in structure_rows
        ),
        "runtime": runtime_rows,
    }
    (args.root / "results" / "core_extension_summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
