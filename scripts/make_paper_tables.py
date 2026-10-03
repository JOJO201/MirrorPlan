#!/usr/bin/env python3
"""Render LaTeX tables directly from machine-readable result files."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
OUT = ROOT / "paper" / "generated"


def rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write(name: str, content: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    summary = rows(ROOT / "results" / "summary.csv")
    methods = ["factor_hybrid", "bundle_greedy", "peeling", "impact", "random"]
    labels = {
        "factor_hybrid": "Exact",
        "bundle_greedy": "Bundle",
        "peeling": "Peeling",
        "impact": "Impact",
        "random": "Random",
    }
    by_key = {(row["budget_fraction"], row["method"]): row for row in summary}
    fractions = sorted({row["budget_fraction"] for row in summary}, key=float)
    lines = [
        r"\begin{tabular}{rccccc}",
        r"\toprule",
        "Budget & " + " & ".join(labels[method] for method in methods) + r" \\",
        r"\midrule",
    ]
    for fraction in fractions:
        values = [
            100 * float(by_key[(fraction, method)]["mean_recovered_fraction"])
            for method in methods
        ]
        rendered = [f"\\textbf{{{value:.1f}}}" if index == 0 else f"{value:.1f}" for index, value in enumerate(values)]
        lines.append(f"{100 * float(fraction):.0f}\\% & " + " & ".join(rendered) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("main_results.tex", "\n".join(lines))

    structure = rows(ROOT / "results" / "structure_by_event.csv")
    structure_lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Event & Deleted & Relevant & Affected & Multi-anc. & Max comp. \\",
        r"\midrule",
    ]
    for row in structure:
        structure_lines.append(
            f"{row['event']} & {int(row['deleted_count']):,} & "
            f"{int(row['candidate_count']):,} & {int(row['affected_targets']):,} & "
            f"{int(row['multi_ancestor_targets']):,} & {int(row['largest_component']):,} \\\\"
        )
    structure_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("event_structure.tex", "\n".join(structure_lines))

    midpoint = (len(structure) + 1) // 2
    compact_structure_lines = [
        r"\begin{tabular}{lrrrr@{\hspace{14pt}}lrrrr}",
        r"\toprule",
        r"Event & $|C|$ & Affected & Multi & Max comp. & "
        r"Event & $|C|$ & Affected & Multi & Max comp. \\",
        r"\midrule",
    ]
    for left, right in zip(structure[:midpoint], structure[midpoint:]):
        compact_structure_lines.append(
            f"{left['event']} & {int(left['candidate_count']):,} & "
            f"{int(left['affected_targets']):,} & "
            f"{int(left['multi_ancestor_targets']):,} & "
            f"{int(left['largest_component']):,} & "
            f"{right['event']} & {int(right['candidate_count']):,} & "
            f"{int(right['affected_targets']):,} & "
            f"{int(right['multi_ancestor_targets']):,} & "
            f"{int(right['largest_component']):,} \\\\"
        )
    compact_structure_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("event_structure_compact.tex", "\n".join(compact_structure_lines))

    alert = rows(ROOT / "results" / "alert_recall_summary.csv")
    alert_lines = [
        r"\begin{tabular}{rccc}",
        r"\toprule",
        r"Alert recall & Mean restored & 95\% CI & Median \\",
        r"\midrule",
    ]
    for row in alert:
        alert_lines.append(
            f"{100 * float(row['alert_recall']):.0f}\\% & "
            f"{100 * float(row['mean_restored_fraction']):.1f}\\% & "
            f"[{100 * float(row['ci95_low']):.1f}, {100 * float(row['ci95_high']):.1f}]\\% & "
            f"{100 * float(row['median_restored_fraction']):.1f}\\% \\\\"
        )
    alert_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("alert_recall.tex", "\n".join(alert_lines))

    runtime = rows(ROOT / "results" / "runtime_summary.csv")
    runtime_lines = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Exact backend & Median & 95th percentile & Maximum \\",
        r"\midrule",
    ]
    runtime_labels = {"factor_hybrid": "FactorHybrid", "milp_exact": "Global MILP"}
    for row in runtime:
        runtime_lines.append(
            f"{runtime_labels[row['method']]} & "
            f"{1000 * float(row['median_pair_runtime_seconds']):.2f} ms & "
            f"{1000 * float(row['p95_pair_runtime_seconds']):.2f} ms & "
            f"{1000 * float(row['max_pair_runtime_seconds']):.2f} ms \\\\"
        )
    runtime_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("runtime.tex", "\n".join(runtime_lines))

    contrasts = rows(ROOT / "results" / "paired_contrasts.csv")
    contrast_key = {
        (row["budget_fraction"], row["baseline"]): row for row in contrasts
    }
    contrast_lines = [
        r"\begin{tabular}{rcrcr}",
        r"\toprule",
        r"Budget & \multicolumn{2}{c}{vs. Impact} & \multicolumn{2}{c}{vs. Peeling} \\",
        r" & Mean gain & Better & Mean gain & Better \\",
        r"\midrule",
    ]
    for fraction in fractions:
        impact = contrast_key[(fraction, "impact")]
        peeling = contrast_key[(fraction, "peeling")]
        contrast_lines.append(
            f"{100 * float(fraction):.0f}\\% & "
            f"{100 * float(impact['mean_paired_gain']):.2f} pp & "
            f"{impact['events_strictly_better']}/16 & "
            f"{100 * float(peeling['mean_paired_gain']):.2f} pp & "
            f"{peeling['events_strictly_better']}/16 \\\\"
        )
    contrast_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("paired_gains.tex", "\n".join(contrast_lines))

    mechanism = rows(ROOT / "results" / "mechanism_summary.csv")
    mechanism_lines = [
        r"\begin{tabular}{rcccc}",
        r"\toprule",
        r"Budget & Core quota & Multi value & Gain & Better \\",
        r"\midrule",
    ]
    for row in mechanism:
        mechanism_lines.append(
            f"{100 * float(row['budget_fraction']):.0f}\\% & "
            f"{100 * float(row['mean_exact_core_budget_fraction']):.1f}\\% & "
            f"{100 * float(row['mean_exact_multi_value_fraction']):.1f}\\% & "
            f"{100 * float(row['mean_paired_recovery_gain']):.2f} pp & "
            f"{row['events_strictly_better']}/16 \\\\"
        )
    mechanism_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("mechanism.tex", "\n".join(mechanism_lines))

    core_structure = rows(ROOT / "results" / "core_structure.csv")
    core_structure_lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Event & $|C|$ & $|K|$ & $|K|/|C|$ & Core comps. & Max comp. \\",
        r"\midrule",
    ]
    for row in core_structure:
        core_structure_lines.append(
            f"{row['event']} & {row['candidates']} & {row['core_candidates']} & "
            f"{100 * float(row['core_fraction']):.1f}\\% & "
            f"{row['core_components']} & {row['max_core_component']} \\\\"
        )
    core_structure_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("core_structure.tex", "\n".join(core_structure_lines))

    stress_rows = rows(ROOT / "results" / "alert_stress_summary.csv")
    stress_key = {
        (row["alert_recall"], row["mechanism"]): row for row in stress_rows
    }
    alert_stress_lines = [
        r"\begin{tabular}{rccc}",
        r"\toprule",
        r"Recall & Uniform & Owner-clustered & Impact-targeted \\",
        r"\midrule",
    ]
    for recall in sorted({row["alert_recall"] for row in stress_rows}, key=float):
        rendered = []
        for method in ("uniform", "owner_clustered", "impact_targeted"):
            row = stress_key[(recall, method)]
            rendered.append(
                f"{100 * float(row['mean_restored_fraction']):.1f} "
                f"[{100 * float(row['ci95_low']):.1f}, "
                f"{100 * float(row['ci95_high']):.1f}]"
            )
        alert_stress_lines.append(
            f"{100 * float(recall):.0f}\\% & " + " & ".join(rendered) + r" \\"
        )
    alert_stress_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("alert_stress.tex", "\n".join(alert_stress_lines))

    core_runtime_rows = rows(ROOT / "results" / "core_runtime_summary.csv")
    core_runtime_lines = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Backend & Median & 95th percentile & Maximum \\",
        r"\midrule",
    ]
    runtime_names = {
        "core_factor": "CoreFactor",
        "factor_hybrid": "FactorHybrid",
        "milp_exact": "Global MILP",
    }
    for row in core_runtime_rows:
        core_runtime_lines.append(
            f"{runtime_names[row['method']]} & "
            f"{1000 * float(row['median_pair_runtime_seconds']):.2f} ms & "
            f"{1000 * float(row['p95_pair_runtime_seconds']):.2f} ms & "
            f"{1000 * float(row['max_pair_runtime_seconds']):.2f} ms \\\\"
        )
    core_runtime_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("core_runtime.tex", "\n".join(core_runtime_lines))

    certificate = rows(ROOT / "results" / "certificate_summary.csv")
    certificate_lines = [
        r"\begin{tabular}{rrrrr}",
        r"\toprule",
        r"Budget & Direct opt. & Mean ratio & Min. ratio & MILP calls \\",
        r"\midrule",
    ]
    for row in certificate:
        certificate_lines.append(
            f"{100 * float(row['budget_fraction']):.0f}\\% & "
            f"{row['bundle_certified_optimal']}/16 & "
            f"{100 * float(row['mean_certified_ratio']):.2f}\\% & "
            f"{100 * float(row['minimum_certified_ratio']):.2f}\\% & "
            f"{row['escalated_to_milp']} \\\\"
        )
    certificate_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("certificate.tex", "\n".join(certificate_lines))

    complete_certificate = rows(
        ROOT / "results" / "complete_certificate_summary.csv"
    )
    proof_stage_names = {
        "bundle_root": "Bundle root",
        "exact_root": "Exact root",
        "branch_charge": "Branch charge",
    }
    proof_cascade_lines = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Closure stage & Pairs & Nodes & Compressed bytes \\",
        r"\midrule",
    ]
    for row in complete_certificate:
        proof_cascade_lines.append(
            f"{proof_stage_names[row['proof_stage']]} & "
            f"{row['event_budget_pairs']} & {row['total_nodes']} & "
            f"{int(row['total_proof_bytes']):,} \\\\"
        )
    proof_cascade_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("proof_cascade.tex", "\n".join(proof_cascade_lines))

    gap = rows(ROOT / "results" / "gap_decomposition_summary.csv")
    gap_focus = [
        row
        for row in gap
        if row["budget_fraction"] == "0.1000" and row["alert_recall"] == "0.90"
    ]
    gap_names = {
        "uniform": "Uniform",
        "owner_clustered": "Owner-clustered",
        "impact_targeted": "Impact-targeted",
    }
    gap_focus_lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Miss mechanism & Recovered & Alert & Capacity & Allocation \\",
        r"\midrule",
    ]
    for row in gap_focus:
        gap_focus_lines.append(
            f"{gap_names[row['mechanism']]} & "
            f"{100 * float(row['mean_recovered_fraction']):.2f}\\% & "
            f"{100 * float(row['mean_alert_gap_fraction']):.2f}\\% & "
            f"{100 * float(row['mean_capacity_gap_fraction']):.2f}\\% & "
            f"{100 * float(row['mean_allocation_gap_fraction']):.3f}\\% \\\\"
        )
    gap_focus_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("gap_focus.tex", "\n".join(gap_focus_lines))

    gap_complete_lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Mechanism & Recall & Recovered & Alert & Capacity & Allocation \\",
        r"\midrule",
    ]
    for gap_mechanism in ("uniform", "owner_clustered", "impact_targeted"):
        for row in gap:
            if (
                row["budget_fraction"] != "0.1000"
                or row["mechanism"] != gap_mechanism
            ):
                continue
            gap_complete_lines.append(
                f"{gap_names[gap_mechanism]} & "
                f"{100 * float(row['alert_recall']):.0f}\\% & "
                f"{100 * float(row['mean_recovered_fraction']):.2f}\\% & "
                f"{100 * float(row['mean_alert_gap_fraction']):.2f}\\% & "
                f"{100 * float(row['mean_capacity_gap_fraction']):.2f}\\% & "
                f"{100 * float(row['mean_allocation_gap_fraction']):.3f}\\% \\\\"
            )
        if gap_mechanism != "impact_targeted":
            gap_complete_lines.append(r"\addlinespace")
    gap_complete_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write("gap_decomposition.tex", "\n".join(gap_complete_lines))

    structure_summary = json.loads(
        (ROOT / "results" / "structure_summary.json").read_text()
    )
    structure_macros = [
        rf"\newcommand{{\MultiAncestor}}{{{100 * structure_summary['multi_ancestor_fraction']:.1f}\%}}",
        rf"\newcommand{{\MultiAncestorCount}}{{{structure_summary['multi_ancestor_targets']:,}}}",
    ]

    headline = json.loads((ROOT / "results" / "headline.json").read_text())
    core = json.loads(
        (ROOT / "results" / "core_extension_summary.json").read_text()
    )
    stress = json.loads(
        (ROOT / "results" / "alert_stress_headline.json").read_text()
    )
    certificate_headline = json.loads(
        (ROOT / "results" / "certificate_headline.json").read_text()
    )
    complete_certificate_headline = json.loads(
        (ROOT / "results" / "complete_certificate_headline.json").read_text()
    )
    gap_headline = json.loads(
        (ROOT / "results" / "gap_headline.json").read_text()
    )
    core_runtime = {
        row["method"]: row for row in core["runtime"]
    }
    stress_summary = {
        (row["mechanism"], row["alert_recall"]): row
        for row in stress["summary"]
    }
    mechanism_primary = next(
        row
        for row in mechanism
        if row["budget_fraction"] == "0.1000"
    )
    certificate_ten = next(
        row
        for row in certificate_headline["by_budget"]
        if row["budget_fraction"] == "0.1000"
    )
    gap_summary = {
        (row["mechanism"], row["alert_recall"]): row
        for row in gap_headline["focus_summary"]
    }
    uniform_gap = gap_summary[("uniform", "0.90")]
    targeted_gap = gap_summary[("impact_targeted", "0.90")]
    gap_runs = rows(ROOT / "results" / "raw" / "gap_extension_runs.csv")
    positive_gap_runs = [
        row for row in gap_runs if int(row["allocation_gap"]) > 0
    ]
    may_positive_gap_runs = [
        row for row in positive_gap_runs if row["event"] == "0507"
    ]
    max_allocation_gap = max(
        float(row["allocation_gap_fraction"]) for row in gap_runs
    )
    macros = [
        rf"\newcommand{{\NumEvents}}{{{headline['events']}}}",
        rf"\newcommand{{\NumAffected}}{{{headline['total_affected_targets']:,}}}",
        rf"\newcommand{{\OracleChecks}}{{{headline['oracle_checks']}}}",
        rf"\newcommand{{\BundleExact}}{{{headline['bundle_greedy_exact_pairs']}}}",
        rf"\newcommand{{\CoreCandidates}}{{{core['total_core_candidates']:,}}}",
        rf"\newcommand{{\CoreFraction}}{{{100 * core['core_candidate_fraction']:.1f}\%}}",
        rf"\newcommand{{\CoreSmallEvents}}{{{core['events_with_core_at_most_39']}}}",
        rf"\newcommand{{\CoreMedianMs}}{{{1000 * core_runtime['core_factor']['median_pair_runtime_seconds']:.2f}}}",
        rf"\newcommand{{\UniformNinety}}{{{100 * stress_summary[('uniform', '0.90')]['mean_restored_fraction']:.1f}\%}}",
        rf"\newcommand{{\TargetedNinety}}{{{100 * stress_summary[('impact_targeted', '0.90')]['mean_restored_fraction']:.1f}\%}}",
        rf"\newcommand{{\UniformSeventy}}{{{100 * stress_summary[('uniform', '0.70')]['mean_restored_fraction']:.1f}\%}}",
        rf"\newcommand{{\TargetedSeventy}}{{{100 * stress_summary[('impact_targeted', '0.70')]['mean_restored_fraction']:.1f}\%}}",
        rf"\newcommand{{\MechanismGain}}{{{100 * float(mechanism_primary['mean_paired_recovery_gain']):.2f}}}",
        rf"\newcommand{{\MechanismCoreQuota}}{{{100 * float(mechanism_primary['mean_exact_core_budget_fraction']):.1f}\%}}",
        rf"\newcommand{{\MechanismMultiValue}}{{{100 * float(mechanism_primary['mean_exact_multi_value_fraction']):.1f}\%}}",
        rf"\newcommand{{\CertificatePairs}}{{{certificate_headline['event_budget_pairs']}}}",
        rf"\newcommand{{\CertificateDirect}}{{{certificate_headline['bundle_certified_optimal']}}}",
        rf"\newcommand{{\CertificateEscalations}}{{{certificate_headline['escalated_to_milp']}}}",
        rf"\newcommand{{\CertificateMeanRatio}}{{{100 * certificate_headline['mean_certified_ratio']:.2f}\%}}",
        rf"\newcommand{{\CertificateMinRatio}}{{{100 * certificate_headline['minimum_certified_ratio']:.2f}\%}}",
        rf"\newcommand{{\CertificateTenDirect}}{{{certificate_ten['bundle_certified_optimal']}}}",
        rf"\newcommand{{\CertificateTenMinRatio}}{{{100 * certificate_ten['minimum_certified_ratio']:.2f}\%}}",
        rf"\newcommand{{\CompleteCertified}}{{{complete_certificate_headline['event_budget_pairs']}}}",
        rf"\newcommand{{\ExactRootCertified}}{{{complete_certificate_headline['exact_root']}}}",
        rf"\newcommand{{\BranchCertified}}{{{complete_certificate_headline['branch_charge']}}}",
        rf"\newcommand{{\LargestProofNodes}}{{{complete_certificate_headline['largest_proof_nodes']}}}",
        rf"\newcommand{{\LargestProofDepth}}{{{complete_certificate_headline['largest_proof_depth']}}}",
        rf"\newcommand{{\ProofTotalBytes}}{{{complete_certificate_headline['total_compressed_bytes']:,}}}",
        rf"\newcommand{{\ProofMedianVerifyMs}}{{{1000 * complete_certificate_headline['median_verification_runtime_seconds']:.2f}}}",
        rf"\newcommand{{\GapUniformRecovered}}{{{100 * uniform_gap['mean_recovered_fraction']:.2f}\%}}",
        rf"\newcommand{{\GapUniformAlert}}{{{100 * uniform_gap['mean_alert_gap_fraction']:.2f}\%}}",
        rf"\newcommand{{\GapUniformCapacity}}{{{100 * uniform_gap['mean_capacity_gap_fraction']:.2f}\%}}",
        rf"\newcommand{{\GapUniformAllocation}}{{{100 * uniform_gap['mean_allocation_gap_fraction']:.3f}\%}}",
        rf"\newcommand{{\GapTargetedRecovered}}{{{100 * targeted_gap['mean_recovered_fraction']:.2f}\%}}",
        rf"\newcommand{{\GapTargetedAlert}}{{{100 * targeted_gap['mean_alert_gap_fraction']:.2f}\%}}",
        rf"\newcommand{{\GapTargetedCapacity}}{{{100 * targeted_gap['mean_capacity_gap_fraction']:.2f}\%}}",
        rf"\newcommand{{\GapTargetedAllocation}}{{{100 * targeted_gap['mean_allocation_gap_fraction']:.3f}\%}}",
        rf"\newcommand{{\GapPositiveRows}}{{{len(positive_gap_runs):,}}}",
        rf"\newcommand{{\GapPositiveShare}}{{{100 * len(positive_gap_runs) / len(gap_runs):.2f}\%}}",
        rf"\newcommand{{\GapMayPositiveShare}}{{{100 * len(may_positive_gap_runs) / len(positive_gap_runs):.1f}\%}}",
        rf"\newcommand{{\GapMaxAllocation}}{{{100 * max_allocation_gap:.2f}\%}}",
        *structure_macros,
    ]
    write("numbers.tex", "\n".join(macros))


if __name__ == "__main__":
    main()
