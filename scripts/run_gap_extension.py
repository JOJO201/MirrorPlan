#!/usr/bin/env python3
"""Run the frozen post-hoc alert/capacity/allocation gap extension."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml

from mirrorplan.alerts import candidate_impact, construct_alert_set, restrict_to_alerts
from mirrorplan.algorithms import bundle_greedy, milp_exact
from mirrorplan.instance import load_instance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Recompute event shards even when a valid shard already exists.",
    )
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def expected_event_rows(protocol: dict) -> int:
    return (
        len(protocol["budget_fractions"])
        * len(protocol["alert_recall"])
        * sum(int(settings["seeds"]) for settings in protocol["mechanisms"].values())
    )


def valid_shard(
    path: Path,
    event: str,
    protocol_hash: str,
    expected_rows: int,
) -> bool:
    if not path.exists():
        return False
    rows = read_rows(path)
    return (
        len(rows) == expected_rows
        and {row["event"] for row in rows} == {event}
        and {row["protocol_sha256"] for row in rows} == {protocol_hash}
    )


def run_event(
    root_text: str,
    event: str,
    protocol: dict,
    protocol_hash: str,
) -> tuple[str, list[dict], int, int]:
    root = Path(root_text)
    instance = load_instance(root / "data" / "instances" / f"event_{event}.json.gz")
    candidates = set(instance.candidates)
    scores = candidate_impact(instance)
    total_impact = sum(scores.values())
    total = instance.affected_targets
    alert_cache = {}
    solution_cache = {}
    rows: list[dict] = []

    for mechanism, settings in protocol["mechanisms"].items():
        for recall_value in protocol["alert_recall"]:
            recall = float(recall_value)
            for seed in range(int(settings["seeds"])):
                alerted = construct_alert_set(instance, recall, mechanism, seed=seed)
                alert_key = frozenset(alerted)
                if alert_key not in alert_cache:
                    restricted = restrict_to_alerts(instance, alerted)
                    alert_cache[alert_key] = (restricted, restricted.affected_targets)
                restricted, alert_ceiling = alert_cache[alert_key]
                missed = candidates - alerted
                missed_impact_share = (
                    sum(scores[candidate] for candidate in missed) / total_impact
                    if total_impact
                    else 0.0
                )

                for budget_value in protocol["budget_fractions"]:
                    budget_fraction = float(budget_value)
                    budget = max(1, math.ceil(budget_fraction * len(candidates)))
                    effective_budget = min(budget, len(restricted.candidates))
                    solution_key = (alert_key, budget)
                    if solution_key not in solution_cache:
                        exact = milp_exact(restricted, effective_budget)
                        deployed = bundle_greedy(restricted, effective_budget)
                        solution_cache[solution_key] = (exact, deployed)
                    exact, deployed = solution_cache[solution_key]

                    alert_gap = total - alert_ceiling
                    capacity_gap = alert_ceiling - exact.value
                    allocation_gap = exact.value - deployed.value
                    if min(alert_gap, capacity_gap, allocation_gap) < 0:
                        raise AssertionError(
                            f"Negative gap for {event}/{mechanism}/{recall}/{seed}/"
                            f"{budget_fraction}: {(alert_gap, capacity_gap, allocation_gap)}"
                        )
                    if alert_gap + capacity_gap + allocation_gap + deployed.value != total:
                        raise AssertionError(
                            f"Gap identity failed for {event}/{mechanism}/{recall}/"
                            f"{seed}/{budget_fraction}"
                        )

                    rows.append(
                        {
                            "protocol_sha256": protocol_hash,
                            "event": event,
                            "mechanism": mechanism,
                            "alert_recall": f"{recall:.2f}",
                            "seed": seed,
                            "budget_fraction": f"{budget_fraction:.4f}",
                            "budget": budget,
                            "effective_budget": effective_budget,
                            "original_candidates": len(candidates),
                            "alerted_candidates": len(alerted),
                            "restricted_candidates": len(restricted.candidates),
                            "missed_owners": len(
                                {candidate.split("/", 1)[0] for candidate in missed}
                            ),
                            "missed_impact_share": missed_impact_share,
                            "all_affected_targets": total,
                            "alert_recoverable_targets": alert_ceiling,
                            "exact_value": exact.value,
                            "bundle_value": deployed.value,
                            "alert_gap": alert_gap,
                            "capacity_gap": capacity_gap,
                            "allocation_gap": allocation_gap,
                            "recovered_value": deployed.value,
                            "alert_gap_fraction": alert_gap / total,
                            "capacity_gap_fraction": capacity_gap / total,
                            "allocation_gap_fraction": allocation_gap / total,
                            "recovered_fraction": deployed.value / total,
                            "exact_runtime_seconds": exact.runtime_seconds,
                            "bundle_runtime_seconds": deployed.runtime_seconds,
                        }
                    )

    return event, rows, len(alert_cache), len(solution_cache)


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

    root = args.root.resolve()
    protocol_path = root / "protocols" / "gap_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen":
        raise SystemExit("Refusing gap run: protocol is not frozen")
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    per_event_expected = expected_event_rows(protocol)
    shard_dir = root / "results" / "raw" / "gap_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    events = list(map(str, protocol["events"]))
    pending = []
    for event in events:
        shard = shard_dir / f"event_{event}.csv"
        if not args.no_resume and valid_shard(
            shard, event, protocol_hash, per_event_expected
        ):
            print(f"event {event}: reused {per_event_expected} rows", flush=True)
        else:
            pending.append(event)

    if args.workers == 1:
        completed = (
            run_event(str(root), event, protocol, protocol_hash) for event in pending
        )
        for event, rows, alert_sets, solved_pairs in completed:
            write_rows(shard_dir / f"event_{event}.csv", rows)
            print(
                f"event {event}: wrote {len(rows)} rows from {alert_sets} alert sets "
                f"and {solved_pairs} exact budget pairs",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    run_event, str(root), event, protocol, protocol_hash
                ): event
                for event in pending
            }
            for future in as_completed(futures):
                event, rows, alert_sets, solved_pairs = future.result()
                write_rows(shard_dir / f"event_{event}.csv", rows)
                print(
                    f"event {event}: wrote {len(rows)} rows from {alert_sets} alert "
                    f"sets and {solved_pairs} exact budget pairs",
                    flush=True,
                )

    all_rows = []
    for event in events:
        shard = shard_dir / f"event_{event}.csv"
        if not valid_shard(shard, event, protocol_hash, per_event_expected):
            raise AssertionError(f"Invalid or incomplete shard: {shard}")
        all_rows.extend(read_rows(shard))

    expected_rows = int(protocol["completeness_gate"]["expected_rows"])
    if len(all_rows) != expected_rows:
        raise AssertionError(f"Expected {expected_rows} rows, got {len(all_rows)}")
    output = root / "results" / "raw" / "gap_extension_runs.csv"
    write_rows(output, all_rows)
    print(f"status passed\nprotocol_sha256 {protocol_hash}\nrows {len(all_rows)}")


if __name__ == "__main__":
    main()
