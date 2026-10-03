#!/usr/bin/env python3
"""Retain the primary study and add bounded post-review measurements."""

import argparse
import csv
import json
import math
import platform
import statistics
import sys
from collections import Counter, defaultdict
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import matplotlib.pyplot as plt
import numpy as np
import yaml

from analyze_results import bootstrap_mean
from deterministic_plots import configure_deterministic_pdf
from mirrorplan.algorithms import bundle_greedy, milp_exact
from mirrorplan.certificates import (
    audit_branch_charge_certificate,
    audit_charge_certificate,
    read_branch_certificate,
    read_certificate,
)
from mirrorplan.instance import load_instance, objective
from mirrorplan.planner import certify_or_escalate


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
    return {
        (r["event"], r["budget_fraction"], r["method"]): r
        for r in read_rows(root / "results/raw/main_runs.csv")
        if r["method"] != "random"
    }


def measure(root, primary, protocol, retained):
    settings = protocol["runtime"]
    raw, loads = [], []
    methods = ("bundle_greedy", "milp_exact", "certify_or_escalate")
    repetitions = int(settings["measured_repetitions"])
    warmups = int(settings["warmups"])
    for event in map(str, primary["population"]["events"]):
        path = root / f"data/instances/event_{event}.json.gz"
        for repetition in range(warmups + repetitions):
            started = perf_counter()
            instance = load_instance(path)
            elapsed = perf_counter() - started
            if repetition >= warmups:
                loads.append({"event": event, "repetition": repetition - warmups,
                              "load_seconds": elapsed})
        for fraction in primary["budgets"]["fractions"]:
            fraction_key = f"{float(fraction):.4f}"
            budget = max(1, math.ceil(float(fraction) * len(instance.candidates)))
            exact_value = int(retained[(event, fraction_key, "factor_hybrid")]["value"])
            for repetition in range(-warmups, repetitions):
                rotation = repetition % len(methods)
                order = methods[rotation:] + methods[:rotation]
                for method in order:
                    started = perf_counter()
                    if method == "certify_or_escalate":
                        result = certify_or_escalate(
                            instance, budget, int(settings["certificate_scale"]),
                            int(settings["node_limit"]),
                        )
                    else:
                        result = (bundle_greedy if method == "bundle_greedy"
                                  else milp_exact)(instance, budget)
                    elapsed = perf_counter() - started
                    expected_method = ("bundle_greedy" if method == "bundle_greedy"
                                       else "factor_hybrid")
                    expected = int(retained[(event, fraction_key, expected_method)]["value"])
                    if result.value != expected or objective(instance, result.selected) != expected:
                        raise AssertionError(f"Objective drift: {event}/{fraction_key}/{method}")
                    if repetition >= 0:
                        raw.append({
                            "event": event, "budget_fraction": fraction_key,
                            "budget": budget, "method": method, "repetition": repetition,
                            "value": result.value, "exact_value": exact_value,
                            "decision_seconds": elapsed,
                            "proof_stage": getattr(result, "proof_stage", "not_applicable"),
                            "phase_seconds": json.dumps(getattr(result, "stage_seconds", {}), sort_keys=True),
                        })
            print(f"measured {event} quota {fraction_key}", flush=True)
    write_rows(root / "results/raw/fse_decision_runtime.csv", raw)
    write_rows(root / "results/raw/fse_instance_load_runtime.csv", loads)
    metadata = {
        "python": sys.version.split()[0], "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": {name: version(name) for name in ("numpy", "scipy", "matplotlib")},
        "protocol": "protocols/fse_revision.yaml",
        "decision_rows": len(raw), "load_rows": len(loads),
        "all_objectives_match_retained_results": True,
    }
    (root / "results/fse_runtime_environment.json").write_text(json.dumps(metadata, indent=2) + "\n")


def analyze(root, primary, protocol, retained, use_retained_cases=False):
    events = list(map(str, primary["population"]["events"]))
    fraction = f'{float(protocol["analysis"]["primary_quota"]):.4f}'
    seed = int(protocol["analysis"]["bootstrap_seed"])
    contrasts = []
    populations = [("all", events), ("without_0507", [e for e in events if e != "0507"])]
    populations += [(f"without_{e}", [x for x in events if x != e]) for e in events if e != "0507"]
    for population, selected_events in populations:
        for baseline in ("impact", "peeling", "bundle_greedy"):
            differences = [
                100 * (float(retained[(e, fraction, "factor_hybrid")]["recovered_fraction"])
                       - float(retained[(e, fraction, baseline)]["recovered_fraction"]))
                for e in selected_events
            ]
            low, high = bootstrap_mean(differences, seed,
                                      int(protocol["analysis"]["bootstrap_repetitions"]))
            contrasts.append({"population": population, "events": len(selected_events),
                              "baseline": baseline, "mean_gain_pp": statistics.mean(differences),
                              "median_gain_pp": statistics.median(differences),
                              "ci95_low_pp": float(low), "ci95_high_pp": float(high),
                              "strict_wins": sum(d > 0 for d in differences)})
    write_rows(root / "results/fse_event_sensitivity.csv", contrasts)

    cases = []
    case_rows = ([] if use_retained_cases else
                 read_rows(root / "results/raw/complete_certificate_runs.csv"))
    if use_retained_cases:
        integer_fields = ("budget", "bundle_value", "root_integer_upper", "exact_value",
                          "nodes", "added_candidates", "removed_candidates",
                          "gained_target_weight", "lost_target_weight")
        cases = read_rows(root / "results/fse_escalation_cases.csv")
        for case in cases:
            for key in integer_fields:
                case[key] = int(case[key])
    for row in case_rows:
        if row["proof_stage"] == "bundle_root":
            continue
        event, quota = row["event"], row["budget_fraction"]
        instance = load_instance(root / f"data/instances/event_{event}.json.gz")
        key = f"{event}_b{int(round(float(quota) * 10000)):04d}"
        root_proof = read_certificate(root / f"results/certificates/{key}.json.gz")
        root_audit = audit_charge_certificate(instance, root_proof)
        final = read_branch_certificate(root / row["proof_file"])
        final_audit = audit_branch_charge_certificate(instance, final)
        before, after = set(root_proof.selected_indices), set(final.selected_indices)
        index = {u: i for i, u in enumerate(instance.candidates)}
        gained, lost = [], []
        for group in instance.groups:
            members = {index[u] for u in group.members}
            old, new = members <= before, members <= after
            if new and not old:
                gained.append(group)
            if old and not new:
                lost.append(group)
        cases.append({
            "event": event, "budget_fraction": quota, "budget": int(row["budget"]),
            "bundle_value": root_audit.lower_value,
            "root_integer_upper": root_audit.integer_upper_bound,
            "exact_value": final_audit.lower_value,
            "proof_stage": row["proof_stage"], "nodes": final_audit.nodes,
            "added_candidates": len(after - before), "removed_candidates": len(before - after),
            "gained_target_weight": sum(g.weight for g in gained),
            "lost_target_weight": sum(g.weight for g in lost),
            "gained_group_ranks": ";".join(str(len(g.members)) for g in gained),
            "lost_group_ranks": ";".join(str(len(g.members)) for g in lost),
        })
    write_rows(root / "results/fse_escalation_cases.csv", cases)
    table_dir = root / "paper/generated"
    table_dir.mkdir(parents=True, exist_ok=True)
    case_tex = [r"\begin{tabular}{lrrrrrl}", r"\toprule",
                r"Event & Quota & $B$ & Bundle & Root UB & Exact & Proof \\", r"\midrule"]
    for r in cases:
        case_tex.append(f'{r["event"]} & {100*float(r["budget_fraction"]):.0f}\\% & {r["budget"]} & '
                        f'{r["bundle_value"]} & {r["root_integer_upper"]} & {r["exact_value"]} & '
                        + ("Branch" if r["proof_stage"] == "branch_charge" else "Root") + r" \\")
    (table_dir / "fse_escalations.tex").write_text("\n".join(case_tex + [r"\bottomrule", r"\end{tabular}"]) + "\n")
    robustness = [r"\begin{tabular}{lrrrr}", r"\toprule",
                  r"Events & $n$ & Exact--Impact (pp) & 95\% interval & Bundle optimal \\", r"\midrule"]
    for label in ("all", "without_0507"):
        r = next(r for r in contrasts if r["population"] == label and r["baseline"] == "impact")
        selected_events = events if label == "all" else [e for e in events if e != "0507"]
        pairs = [(e, f'{float(q):.4f}') for e in selected_events for q in primary["budgets"]["fractions"]]
        wins = sum(retained[(e, q, "bundle_greedy")]["value"] == retained[(e, q, "factor_hybrid")]["value"]
                   for e, q in pairs)
        robustness.append(("All" if label == "all" else "Without May 7")
                          + f' & {r["events"]} & {r["mean_gain_pp"]:.2f} & '
                          + f'[{r["ci95_low_pp"]:.2f}, {r["ci95_high_pp"]:.2f}] & {wins}/{len(pairs)}' + r" \\")
    (table_dir / "fse_sensitivity.tex").write_text("\n".join(robustness + [r"\bottomrule", r"\end{tabular}"]) + "\n")

    timings = read_rows(root / "results/raw/fse_decision_runtime.csv")
    pair_runs = defaultdict(list)
    for row in timings:
        pair_runs[(row["event"], row["budget_fraction"], row["method"])].append(float(row["decision_seconds"]))
    pair_medians = {key: statistics.median(values) for key, values in pair_runs.items()}
    summaries = []
    for method in ("bundle_greedy", "milp_exact", "certify_or_escalate"):
        values = [v * 1000 for (e, q, m), v in pair_medians.items() if m == method]
        summaries.append({"method": method, "pairs": len(values), "median_ms": statistics.median(values),
                          "p95_ms": float(np.percentile(values, 95)), "maximum_ms": max(values)})
    write_rows(root / "results/fse_decision_runtime_summary.csv", summaries)
    runtime_tex = [r"\begin{tabular}{lrrr}", r"\toprule", r"Method & Median (ms) & P95 (ms) & Max (ms) \\", r"\midrule"]
    names = {"bundle_greedy": "Bundle", "milp_exact": "Global MILP", "certify_or_escalate": "MirrorPlan with audit"}
    for r in summaries:
        runtime_tex.append(f'{names[r["method"]]} & {r["median_ms"]:.3f} & {r["p95_ms"]:.3f} & {r["maximum_ms"]:.3f}' + r" \\")
    (table_dir / "fse_runtime.tex").write_text("\n".join(runtime_tex + [r"\bottomrule", r"\end{tabular}"]) + "\n")
    ratios = [pair_medians[(e, q, "certify_or_escalate")] / pair_medians[(e, q, "milp_exact")]
              for e, q, m in pair_medians if m == "certify_or_escalate"]
    load_runs = defaultdict(list)
    for row in read_rows(root / "results/raw/fse_instance_load_runtime.csv"):
        load_runs[row["event"]].append(1000 * float(row["load_seconds"]))
    load_medians = [statistics.median(values) for values in load_runs.values()]
    without = next(r for r in contrasts if r["population"] == "without_0507" and r["baseline"] == "impact")
    impact_loo = [r["mean_gain_pp"] for r in contrasts if r["baseline"] == "impact" and r["population"] != "all"]
    macros = {
        "FSEMirrorMedianMs": summaries[2]["median_ms"], "FSEMILPMedianMs": summaries[1]["median_ms"],
        "FSEPipelineRatio": statistics.median(ratios), "FSEWithoutMayImpactGain": without["mean_gain_pp"],
        "FSEWithoutMayCILow": without["ci95_low_pp"], "FSEWithoutMayCIHigh": without["ci95_high_pp"],
        "FSELOOMin": min(impact_loo), "FSELOOMax": max(impact_loo),
        "FSELoadMedianMs": statistics.median(load_medians),
        "FSELoadMaxMs": max(load_medians),
    }
    (table_dir / "fse_numbers.tex").write_text("\n".join(
        f"\\newcommand{{\\{name}}}{{{value:.2f}}}" for name, value in macros.items()) + "\n")
    payload = {"runtime": summaries, "paired_median_pipeline_to_milp": statistics.median(ratios),
               "without_may7_impact_contrast": without, "escalations": cases,
               "proof_stage_counts": dict(Counter(r["proof_stage"] for r in timings if r["method"] == "certify_or_escalate")),
               "instance_loading_ms": {"median": statistics.median(load_medians),
                                       "maximum": max(load_medians)},
               "post_review": True}
    (root / "results/fse_revision_headline.json").write_text(json.dumps(payload, indent=2) + "\n")

    configure_deterministic_pdf()
    rows = [r for r in read_rows(root / "results/gap_decomposition_summary.csv")
            if r["budget_fraction"] == "0.1000" and r["alert_recall"] == "0.90"]
    figure, axes = plt.subplots(1, 4, figsize=(9.0, 2.6), sharex=True)
    mechanisms = ("uniform", "owner_clustered", "impact_targeted")
    labels = ("Uniform", "Owner-clustered", "Impact-targeted")
    for ax, metric, title, color in zip(axes, ("recovered", "alert_gap", "capacity_gap", "allocation_gap"),
                                       ("Preserved", "Alert gap", "Quota gap", "Allocation gap"),
                                       ("#277F6A", "#B34444", "#7564A5", "#3A75A8"), strict=True):
        for i, mechanism in enumerate(mechanisms):
            r = next(r for r in rows if r["mechanism"] == mechanism)
            key = "mean_recovered_fraction" if metric == "recovered" else f"mean_{metric}_fraction"
            mean = 100 * float(r[key])
            low, high = (100 * float(r[f"{metric}_ci95_{end}"]) for end in ("low", "high"))
            ax.errorbar(mean, i, xerr=[[max(0, mean-low)], [max(0, high-mean)]], fmt="o", color=color, capsize=3)
        ax.set_title(title, fontsize=10)
        ax.set_xlim(-1, 100)
        ax.set_yticks(range(3), labels if ax == axes[0] else [])
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.2)
        ax.set_xlabel("Share (%)")
    figure.tight_layout()
    figure.savefig(root / "results/figures/fse_gap_intervals.pdf", bbox_inches="tight",
                   metadata={"CreationDate": None, "ModDate": None})
    plt.close(figure)
    print(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--analysis-only", action="store_true")
    parser.add_argument("--retained-cases", action="store_true",
                        help="Regenerate case tables from audited aggregate rows, not encoded instances")
    args = parser.parse_args()
    if args.retained_cases and not args.analysis_only:
        parser.error("--retained-cases requires --analysis-only")
    primary = yaml.safe_load((args.root / "protocols/main.yaml").read_text())
    protocol = yaml.safe_load((args.root / "protocols/fse_revision.yaml").read_text())
    if protocol["status"] != "frozen" or not protocol["prior_outcomes_known"]:
        raise SystemExit("FSE extension must be frozen and explicitly post-review")
    retained = retained_values(args.root)
    if not args.analysis_only:
        measure(args.root, primary, protocol, retained)
    analyze(args.root, primary, protocol, retained, args.retained_cases)


if __name__ == "__main__":
    main()
