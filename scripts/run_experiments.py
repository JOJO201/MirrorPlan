#!/usr/bin/env python3
"""Execute the frozen confirmatory protocol and retain raw rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import scipy
import yaml

from mirrorplan.algorithms import (
    bundle_greedy,
    factor_hybrid,
    impact_ranking,
    loss_aware_peeling,
    milp_exact,
    random_selection,
)
from mirrorplan.instance import load_instance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--events", nargs="*", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    protocol = yaml.safe_load(args.protocol.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen":
        raise SystemExit("Refusing confirmatory run: protocol status is not frozen")
    protocol_hash = file_hash(args.protocol)
    configured_events = [str(value) for value in protocol["population"]["events"]]
    requested = set(args.events)
    events = [event for event in configured_events if not requested or event in requested]
    if requested - set(configured_events):
        raise SystemExit(f"Unknown event(s): {sorted(requested - set(configured_events))}")

    output = args.output or args.root / "results" / "raw" / "main_runs.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    selection_path = output.with_name("main_selections.jsonl")
    rows: list[dict] = []
    selections: list[dict] = []
    deterministic = {
        "factor_hybrid": lambda instance, budget: factor_hybrid(
            instance,
            budget,
            component_limit=int(protocol["solver"]["component_enumeration_limit"]),
        ),
        "milp_exact": milp_exact,
        "bundle_greedy": bundle_greedy,
        "peeling": loss_aware_peeling,
        "impact": impact_ranking,
    }
    methods = [
        protocol["methods"]["proposed"],
        protocol["methods"]["independent_oracle"],
        *protocol["methods"]["deterministic_baselines"],
    ]

    for event in events:
        instance_path = args.root / "data" / "instances" / f"event_{event}.json.gz"
        if not instance_path.exists():
            raise SystemExit(f"Missing instance: {instance_path}")
        instance = load_instance(instance_path)
        candidate_count = len(instance.candidates)
        for fraction in protocol["budgets"]["fractions"]:
            budget = min(candidate_count, max(1, math.ceil(float(fraction) * candidate_count)))
            for method in methods:
                solution = deterministic[method](instance, budget)
                row = {
                    "protocol_sha256": protocol_hash,
                    "event": event,
                    "snapshot": instance.snapshot,
                    "budget_fraction": f"{float(fraction):.4f}",
                    "budget": budget,
                    "candidate_count": candidate_count,
                    "affected_targets": instance.affected_targets,
                    "method": method,
                    "seed": "",
                    "value": solution.value,
                    "recovered_fraction": solution.value / instance.affected_targets,
                    "runtime_seconds": solution.runtime_seconds,
                    "optimal": int(solution.optimal),
                }
                rows.append(row)
                selections.append({**row, "selected": list(solution.selected)})
            for seed in range(int(protocol["methods"]["random_seeds"])):
                solution = random_selection(instance, budget, seed)
                row = {
                    "protocol_sha256": protocol_hash,
                    "event": event,
                    "snapshot": instance.snapshot,
                    "budget_fraction": f"{float(fraction):.4f}",
                    "budget": budget,
                    "candidate_count": candidate_count,
                    "affected_targets": instance.affected_targets,
                    "method": "random",
                    "seed": seed,
                    "value": solution.value,
                    "recovered_fraction": solution.value / instance.affected_targets,
                    "runtime_seconds": solution.runtime_seconds,
                    "optimal": 0,
                }
                rows.append(row)

    fieldnames = list(rows[0])
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with selection_path.open("w", encoding="utf-8") as handle:
        for selection in selections:
            handle.write(json.dumps(selection, sort_keys=True) + "\n")

    environment = {
        "protocol_sha256": protocol_hash,
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "scipy": scipy.__version__,
        "rows": len(rows),
    }
    environment_path = output.with_name("environment.json")
    environment_path.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(environment, indent=2))


if __name__ == "__main__":
    main()

