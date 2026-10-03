#!/usr/bin/env python3
"""Measure and rebuild the post-hoc matched-certification comparison."""

import argparse
import csv
import json
import math
import os
import platform
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import numpy as np
import scipy.optimize
import yaml

from mirrorplan.algorithms import bundle_greedy, milp_exact
from mirrorplan.certificates import (
    BranchChargeCertificate,
    audit_branch_charge_certificate,
    audit_charge_certificate,
)
from mirrorplan.instance import load_instance, objective
from mirrorplan.planner import certify_or_escalate, milp_then_certify


ROOT = Path(__file__).parents[1]
CERTIFIED = {"certify_or_escalate", "milp_then_certify"}


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def retained_values(root):
    return {(r["event"], r["budget_fraction"], r["method"]): int(r["value"])
            for r in read_rows(root / "results/raw/main_runs.csv") if r["method"] != "random"}


def measure(root, primary, protocol):
    path = root / "results/raw/matched_certification_runtime.csv"
    if path.exists():
        raise FileExistsError("Retained measurements already exist; use --analysis-only")
    settings = protocol["runtime"]
    methods = tuple(settings["methods"])
    functions = {"bundle_greedy": bundle_greedy, "milp_exact": milp_exact,
                 "certify_or_escalate": certify_or_escalate, "milp_then_certify": milp_then_certify}
    values = retained_values(root)
    scale, limit = int(settings["certificate_scale"]), int(settings["node_limit"])
    warmups, repetitions = int(settings["warmups"]), int(settings["measured_repetitions"])
    metadata = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "machine": platform.machine(), "load_average_at_start": os.getloadavg(),
        "packages": {name: version(name) for name in ("numpy", "scipy", "PyYAML")},
        "thread_environment": {name: os.environ.get(name) for name in
                               ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
        "protocol": "protocols/matched_certification.yaml",
        "protocol_snapshot": protocol,
    }
    rows, pair_index = [], 0
    for event in map(str, primary["population"]["events"]):
        instance = load_instance(root / f"data/instances/event_{event}.json.gz")
        for fraction in primary["budgets"]["fractions"]:
            fraction_key = f"{float(fraction):.4f}"
            budget = max(1, math.ceil(float(fraction) * len(instance.candidates)))
            exact_value = values[(event, fraction_key, "factor_hybrid")]
            for repetition in range(-warmups, repetitions):
                rotation = (pair_index + repetition) % len(methods)
                order = methods[rotation:] + methods[:rotation]
                for order_index, method in enumerate(order):
                    started = perf_counter()
                    result = (functions[method](instance, budget, scale, limit)
                              if method in CERTIFIED else functions[method](instance, budget))
                    elapsed = perf_counter() - started
                    expected = values[(event, fraction_key,
                                       "bundle_greedy" if method == "bundle_greedy" else "factor_hybrid")]
                    if result.value != expected or objective(instance, result.selected) != expected:
                        raise AssertionError(f"Objective drift: {event}/{fraction_key}/{method}")
                    if len(result.selected) > budget or len(set(result.selected)) != len(result.selected):
                        raise AssertionError("Infeasible returned selection")
                    certified, nodes, depth = 0, 0, 0
                    if method in CERTIFIED:
                        checker = (audit_branch_charge_certificate
                                   if isinstance(result.proof, BranchChargeCertificate)
                                   else audit_charge_certificate)
                        audit = checker(instance, result.proof)
                        if not audit.certified_optimal or audit.lower_value != exact_value:
                            raise AssertionError("Returned proof failed independent validation")
                        certified, nodes, depth = 1, getattr(audit, "nodes", 1), getattr(audit, "maximum_depth", 0)
                    if repetition >= 0:
                        rows.append({
                            "event": event, "budget_fraction": fraction_key, "budget": budget,
                            "method": method, "repetition": repetition, "order_index": order_index,
                            "value": result.value, "exact_value": exact_value,
                            "decision_seconds": elapsed, "certified_optimal": certified,
                            "proof_stage": getattr(result, "proof_stage", "not_applicable"),
                            "proof_nodes": nodes, "proof_depth": depth,
                            "phase_seconds": json.dumps(getattr(result, "stage_seconds", {}), sort_keys=True),
                        })
            pair_index += 1
            print(f"{pair_index:02d}/80 event={event} quota={fraction_key}: four methods validated", flush=True)
    write_rows(path, rows)
    metadata["completed_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["load_average_at_end"] = os.getloadavg()
    metadata["rows"] = len(rows)
    (root / "results/matched_certification_environment.json").write_text(json.dumps(metadata, indent=2) + "\n")


def analyze(root, primary, protocol):
    environment = json.loads((root / "results/matched_certification_environment.json").read_text())
    assert environment["protocol_snapshot"] == protocol
    rows = read_rows(root / "results/raw/matched_certification_runtime.csv")
    methods = tuple(protocol["runtime"]["methods"])
    repetitions = int(protocol["runtime"]["measured_repetitions"])
    values = retained_values(root)
    events = list(map(str, primary["population"]["events"]))
    quotas = [f"{float(q):.4f}" for q in primary["budgets"]["fractions"]]
    grouped, seen = defaultdict(list), set()
    for row in rows:
        key = (row["event"], row["budget_fraction"], row["method"])
        unique = (*key, int(row["repetition"]))
        assert unique not in seen
        seen.add(unique)
        elapsed = float(row["decision_seconds"])
        phases = json.loads(row["phase_seconds"])
        assert math.isfinite(elapsed) and elapsed > 0
        assert all(math.isfinite(v) and v >= 0 for v in phases.values())
        assert sum(phases.values()) <= elapsed
        expected_method = "bundle_greedy" if row["method"] == "bundle_greedy" else "factor_hybrid"
        assert int(row["value"]) == values[(key[0], key[1], expected_method)]
        assert int(row["exact_value"]) == values[(key[0], key[1], "factor_hybrid")]
        assert int(row["certified_optimal"]) == int(row["method"] in CERTIFIED)
        grouped[key].append(row)
    assert seen == {(e, q, m, r) for e in events for q in quotas for m in methods for r in range(repetitions)}
    medians = {key: statistics.median(float(r["decision_seconds"]) for r in group) * 1000
               for key, group in grouped.items()}
    summary = []
    for method in methods:
        times = [v for (e, q, m), v in medians.items() if m == method]
        summary.append({"method": method, "pairs": len(times),
                        "median_ms": statistics.median(times),
                        "p95_ms": float(np.quantile(times, 0.95)), "maximum_ms": max(times)})
    write_rows(root / "results/matched_certification_runtime_summary.csv", summary)
    paired = [{"event": e, "budget_fraction": q,
               "heuristic_first_ms": medians[(e, q, "certify_or_escalate")],
               "milp_first_ms": medians[(e, q, "milp_then_certify")],
               "heuristic_over_milp": medians[(e, q, "certify_or_escalate")] / medians[(e, q, "milp_then_certify")]}
              for e in events for q in quotas]
    write_rows(root / "results/matched_certification_paired.csv", paired)
    strata = []
    for quota in quotas:
        pairs = [r for r in paired if r["budget_fraction"] == quota]
        strata.append({"budget_fraction": quota, "events": len(pairs),
                       "heuristic_median_ms": statistics.median(r["heuristic_first_ms"] for r in pairs),
                       "milp_median_ms": statistics.median(r["milp_first_ms"] for r in pairs),
                       "median_paired_ratio": statistics.median(r["heuristic_over_milp"] for r in pairs),
                       "heuristic_faster_events": sum(r["heuristic_over_milp"] < 1 for r in pairs)})
    write_rows(root / "results/matched_certification_by_quota.csv", strata)
    stages = {method: dict(Counter(group[0]["proof_stage"] for (e, q, m), group in grouped.items() if m == method))
              for method in sorted(CERTIFIED)}
    for key, group in grouped.items():
        assert len({(r["proof_stage"], r["proof_nodes"], r["proof_depth"]) for r in group}) == 1
    headline = {
        "pairs": len(events) * len(quotas), "measured_rows": len(rows),
        "all_objectives_match_retained_results": True,
        "all_certified_runs_passed_integer_check": True,
        "median_paired_heuristic_over_certified_milp": statistics.median(r["heuristic_over_milp"] for r in paired),
        "median_paired_heuristic_over_bare_milp": statistics.median(
            medians[(e, q, "certify_or_escalate")] / medians[(e, q, "milp_exact")] for e in events for q in quotas),
        "heuristic_faster_pairs": sum(r["heuristic_over_milp"] < 1 for r in paired),
        "proof_stages_per_pair": stages,
        "proof_nodes_per_80_pairs": {
            method: sum(int(group[0]["proof_nodes"]) for (e, q, m), group in grouped.items() if m == method)
            for method in sorted(CERTIFIED)},
    }
    (root / "results/matched_certification_headline.json").write_text(json.dumps(headline, indent=2) + "\n")
    lookup = {r["method"]: r for r in summary}
    numeric = {
        "MatchedHeuristicMedianMs": lookup["certify_or_escalate"]["median_ms"],
        "MatchedBareMILPMedianMs": lookup["milp_exact"]["median_ms"],
        "MatchedCertifiedMILPMedianMs": lookup["milp_then_certify"]["median_ms"],
        "MatchedBareRatio": headline["median_paired_heuristic_over_bare_milp"],
        "MatchedCertifiedRatio": headline["median_paired_heuristic_over_certified_milp"],
        "MatchedHeuristicTailMs": lookup["certify_or_escalate"]["p95_ms"],
        "MatchedCertifiedMILPTailMs": lookup["milp_then_certify"]["p95_ms"],
        "MatchedSmallHeuristicMs": strata[0]["heuristic_median_ms"],
        "MatchedSmallMILPMs": strata[0]["milp_median_ms"],
        "MatchedLargeHeuristicMs": strata[-1]["heuristic_median_ms"],
        "MatchedLargeMILPMs": strata[-1]["milp_median_ms"],
    }
    lines = [f"\\newcommand{{\\{name}}}{{{value:.2f}}}" for name, value in numeric.items()]
    lines += [f"\\newcommand{{\\MatchedSmallWins}}{{{strata[0]['heuristic_faster_events']}}}"]
    (root / "paper/generated/matched_certification_numbers.tex").write_text("\n".join(lines) + "\n")
    print(json.dumps({"summary": summary, "quota_strata": strata, "headline": headline}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--analysis-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    primary = yaml.safe_load((root / "protocols/main.yaml").read_text())
    protocol = yaml.safe_load((root / "protocols/matched_certification.yaml").read_text())
    if not args.analysis_only:
        measure(root, primary, protocol)
    analyze(root, primary, protocol)


if __name__ == "__main__":
    main()
