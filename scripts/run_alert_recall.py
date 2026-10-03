#!/usr/bin/env python3
"""Run the preregistered false-negative alert sensitivity analysis."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import yaml

from mirrorplan.alerts import construct_alert_set, restrict_to_alerts
from mirrorplan.algorithms import milp_exact
from mirrorplan.instance import load_instance


ROOT = Path(__file__).parents[1]


def main() -> None:
    protocol = yaml.safe_load(
        (ROOT / "protocols" / "alert_recall.yaml").read_text(encoding="utf-8")
    )
    rows = []
    for event in map(str, protocol["events"]):
        instance = load_instance(ROOT / "data" / "instances" / f"event_{event}.json.gz")
        candidates = list(instance.candidates)
        budget = max(
            1,
            math.ceil(
                float(protocol["budget_fraction_of_original_candidates"])
                * len(candidates)
            ),
        )
        for recall_value in protocol["alert_recall"]:
            recall = float(recall_value)
            alert_count = min(len(candidates), round(recall * len(candidates)))
            for seed in range(int(protocol["seeds"])):
                alerted = construct_alert_set(instance, recall, "uniform", seed)
                restricted = restrict_to_alerts(instance, alerted)
                solution = milp_exact(restricted, min(budget, len(restricted.candidates)))
                rows.append(
                    {
                        "event": event,
                        "alert_recall": f"{recall:.2f}",
                        "seed": seed,
                        "original_candidates": len(candidates),
                        "alerted_candidates": alert_count,
                        "budget": budget,
                        "all_affected_targets": instance.affected_targets,
                        "restored_targets": solution.value,
                        "restored_fraction": solution.value / instance.affected_targets,
                    }
                )
    output = ROOT / "results" / "raw" / "alert_recall_runs.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} alert-recall rows to {output}")


if __name__ == "__main__":
    main()
