#!/usr/bin/env python3
"""Regenerate the FSE displays from retained results without running solvers."""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.text import Text
from matplotlib.ticker import FuncFormatter, PercentFormatter

from deterministic_plots import configure_deterministic_pdf


ROOT = Path(__file__).parents[1]
FIGURES = ROOT / "results/figures"
TABLES = ROOT / "paper/generated"
INK, GRAY, LIGHT = "#222222", "#737373", "#D4D4D4"


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def event_label(event):
    return datetime.strptime("2025" + event, "%Y%m%d").strftime("%b %-d")


def save(figure, name):
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    undrawn_ticks = set()
    for ax in figure.axes:
        for axis in (ax.xaxis, ax.yaxis):
            low, high = sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if not low <= tick.get_loc() <= high:
                    undrawn_ticks.update((tick.label1, tick.label2))
    for label in figure.findobj(Text):
        if label in undrawn_ticks or not label.get_visible() or not label.get_text().strip():
            continue
        box = label.get_window_extent(renderer)
        bounds = figure.bbox
        if box.x0 < bounds.x0 - 1 or box.y0 < bounds.y0 - 1 or box.x1 > bounds.x1 + 1 or box.y1 > bounds.y1 + 1:
            raise AssertionError(f"Clipped label in {name}: {label.get_text()!r}")
    figure.savefig(FIGURES / f"{name}.pdf", metadata={"CreationDate": None, "ModDate": None})
    figure.savefig(FIGURES / f"{name}.svg", metadata={"Date": None})
    figure.savefig(FIGURES / f"{name}.png", dpi=300)
    plt.close(figure)


def clean_axis(ax, *, grid="x"):
    ax.spines[["top", "right"]].set_visible(False)
    for spine in ax.spines.values():
        spine.set_color(GRAY)
        spine.set_linewidth(0.6)
    ax.grid(False)
    if grid:
        ax.grid(axis=grid, color="#E8E8E8", linewidth=0.45)
    ax.set_axisbelow(True)
    ax.tick_params(length=2.5, width=0.6, color=GRAY)


def paired_gains():
    rows = [r for r in read_rows(ROOT / "results/raw/main_runs.csv")
            if r["budget_fraction"] == "0.1000" and r["method"] in
            ("factor_hybrid", "impact", "bundle_greedy")]
    values = {(r["event"], r["method"]): r for r in rows}
    events = sorted({r["event"] for r in rows})
    assert len(events) == 16 and len(values) == 48
    gains = {m: np.array([100 * (float(values[(e, "factor_hybrid")]["recovered_fraction"])
                                      - float(values[(e, m)]["recovered_fraction"])) for e in events])
             for m in ("impact", "bundle_greedy")}
    assert all(np.all(g >= 0) for g in gains.values())
    figure, axes = plt.subplots(1, 2, figsize=(5.45, 3.6), sharey=True,
                                gridspec_kw={"width_ratios": [1.65, 1]})
    outlier = events.index("0507")
    for method, name, color, marker, offset, fill in (
        ("impact", "Impact", GRAY, "o", -0.22, "white"),
        ("bundle_greedy", "Bundle", INK, "s", 0.22, INK),
    ):
        yy = np.arange(16) + offset
        axes[0].hlines(yy, 0, gains[method], color=color, linewidth=0.7)
        axes[0].scatter(gains[method], yy, facecolor=fill, edgecolor=color,
                        linewidth=0.7, marker=marker, s=12, label=name, zorder=3)
        if method == "impact":
            for gain, y in zip(gains[method], yy, strict=True):
                if 0 < gain < 0.5:
                    axes[0].annotate(f"+{gain:.2f}", (gain, y), xytext=(7, 0),
                                     textcoords="offset points", va="center", color=color, fontsize=8)
    axes[0].set_xlim(-0.45, 16.5)
    axes[0].set_xticks([0, 5, 10, 15])
    axes[0].set_title("(a) Common comparison scale", loc="left", pad=8)
    axes[0].set_xlabel("Exact minus baseline (pp)")
    axes[0].legend(loc="lower right", frameon=False, handletextpad=0.4, fontsize=8)
    axes[0].annotate("May 7", (gains["impact"][outlier], outlier - 0.22),
                     xytext=(4, -13), textcoords="offset points", color=GRAY, fontsize=8)
    axes[1].hlines(np.arange(16), 0, gains["bundle_greedy"], color=INK, linewidth=0.7)
    axes[1].scatter(gains["bundle_greedy"], np.arange(16), color=INK, marker="s", s=12, zorder=3)
    axes[1].set_xlim(-0.002, 0.075)
    axes[1].set_xticks([0, 0.02, 0.04, 0.06])
    axes[1].set_title("(b) Bundle detail", loc="left", pad=8)
    axes[1].set_xlabel("Exact minus Bundle (pp)\nExpanded scale")
    axes[1].annotate("+1 target", (gains["bundle_greedy"][outlier], outlier),
                     xytext=(-4, -14), ha="right", textcoords="offset points", color=GRAY, fontsize=8)
    for ax in axes:
        ax.set_yticks(range(16), [event_label(e) for e in events])
        ax.set_ylim(15.7, -0.7)
        clean_axis(ax, grid=None)
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)
    figure.subplots_adjust(left=0.13, right=0.98, bottom=0.20, top=0.91, wspace=0.26)
    save(figure, "fse_paired_events")


def runtime_sources():
    matched = ROOT / "results/raw/matched_certification_runtime.csv"
    if matched.exists():
        return matched, ROOT / "results/matched_certification_runtime_summary.csv", (
            ("bundle_greedy", "Bundle", GRAY, "--"),
            ("milp_exact", "Global MILP", GRAY, ":"),
            ("certify_or_escalate", "Heuristic + cert.", INK, "-"),
            ("milp_then_certify", "MILP + cert.", INK, "-."),
        )
    return ROOT / "results/raw/fse_decision_runtime.csv", ROOT / "results/fse_decision_runtime_summary.csv", (
        ("bundle_greedy", "Bundle", GRAY, "--"),
        ("milp_exact", "Global MILP", GRAY, ":"),
        ("certify_or_escalate", "Audited workflow", INK, "-"),
    )


def runtime_distribution():
    source, _, methods = runtime_sources()
    grouped = defaultdict(list)
    for row in read_rows(source):
        grouped[(row["event"], row["budget_fraction"], row["method"])].append(
            float(row["decision_seconds"]) * 1000)
    assert len(grouped) == 80 * len(methods) and all(len(v) == 7 for v in grouped.values())
    medians = [statistics.median(v) for v in grouped.values()]
    left, right = min(medians) * 0.8, max(1050, max(medians) * 1.3)
    figure, (ax, tail) = plt.subplots(2, 1, figsize=(5.45, 3.5), sharex=True,
                                    gridspec_kw={"height_ratios": [2.6, 1.15], "hspace": 0.43})
    for i, (method, name, color, style) in enumerate(methods):
        values = np.sort([statistics.median(v) for (_, _, m), v in grouped.items() if m == method])
        assert len(values) == 80 and values[0] > 0
        ax.step(np.r_[left, values, right], np.r_[0, np.arange(1, 81) / 80, 1],
                where="post", color=color,
                linestyle=style, linewidth=1.2, label=name)
        median, p95 = np.quantile(values, [0.5, 0.95])
        tail.hlines(i, median, values[-1], color=GRAY, linewidth=0.7)
        tail.scatter(median, i, color=INK, marker="o", s=13, zorder=3)
        tail.scatter(p95, i, facecolor="white", edgecolor=INK, linewidth=0.8,
                     marker="o", s=18, zorder=3)
        tail.scatter(values[-1], i, color=INK, marker="|", s=65, linewidth=0.9, zorder=3)
    ax.set_xscale("log")
    ax.set_xlim(left, right)
    ax.set_xticks([v for v in (0.01, 0.1, 1, 10, 100, 1000) if left <= v <= right])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.set_ylim(0, 1.035)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_ylabel("Share of event--quota pairs")
    ax.set_title("(a) Empirical cumulative distribution", loc="left", pad=7)
    ax.legend(loc="lower right", frameon=False, fontsize=8, handlelength=2.7)
    tail.set_title("(b) Median, P95 and maximum", loc="left", pad=7)
    tail.set_yticks(range(len(methods)), [name for _, name, _, _ in methods])
    tail.set_ylim(len(methods) - 0.45, -0.55)
    tail.set_xlabel("Loaded-instance decision time (ms; log scale)")
    tail.tick_params(axis="y", length=0)
    tail.minorticks_off()
    clean_axis(ax, grid="x")
    clean_axis(tail, grid=None)
    tail.spines["left"].set_visible(False)
    tail.tick_params(axis="y", length=0)
    figure.subplots_adjust(left=0.24, right=0.97, bottom=0.16, top=0.92)
    save(figure, "fse_runtime_distribution")


def alert_losses():
    rows = [r for r in read_rows(ROOT / "results/gap_decomposition_summary.csv")
            if r["budget_fraction"] == "0.1000"]
    lookup = {(r["mechanism"], r["alert_recall"]): r for r in rows}
    mechanisms = ("uniform", "owner_clustered", "impact_targeted")
    names = ("Uniform", "Owner-clustered", "Impact-targeted")
    recalls = ("0.50", "0.70", "0.90", "1.00")
    components = (
        ("mean_recovered_fraction", "Preserved", "#555555"),
        ("mean_capacity_gap_fraction", "Quota gap", LIGHT),
        ("mean_alert_gap_fraction", "Alert gap", "#939393"),
        ("mean_allocation_gap_fraction", "Allocation gap", INK),
    )
    figure = plt.figure(figsize=(5.45, 3.95))
    grid = figure.add_gridspec(2, 3, height_ratios=[1.2, 1], hspace=0.64, wspace=0.42)
    for i, (mechanism, name) in enumerate(zip(mechanisms, names, strict=True)):
        ax = figure.add_subplot(grid[0, i])
        bottom = np.zeros(4)
        for field, label, color in components:
            values = 100 * np.array([float(lookup[(mechanism, r)][field]) for r in recalls])
            ax.barh(range(4), values, left=bottom, height=0.60, color=color,
                   edgecolor="white", linewidth=0.35, label=label)
            bottom += values
        assert np.allclose(bottom, 100, atol=1e-8)
        ax.set_title(f"({chr(97+i)}) {name}", loc="left", pad=7)
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 50, 100])
        ax.set_ylim(3.6, -0.6)
        ax.set_yticks(range(4), ["50", "70", "90", "100"])
        ax.set_xlabel("Affected lineages (%)")
        if i == 0:
            ax.set_ylabel("Alert recall (%)")
        clean_axis(ax, grid=None)
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)
        if i == 0:
            handles, labels = ax.get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.53, 1.0),
                  ncol=4, frameon=False, fontsize=7.8, handlelength=1.1, columnspacing=1.0)
    for ax, metric, title in (
        (figure.add_subplot(grid[1, :2]), "recovered", "(d) Preserved at 90% recall"),
        (figure.add_subplot(grid[1, 2]), "allocation_gap", "(e) Allocation gap"),
    ):
        for i, mechanism in enumerate(mechanisms):
            row = lookup[(mechanism, "0.90")]
            field = "mean_recovered_fraction" if metric == "recovered" else f"mean_{metric}_fraction"
            scale = 100 if metric == "recovered" else 100000
            mean = scale * float(row[field])
            low, high = (scale * float(row[f"{metric}_ci95_{bound}"]) for bound in ("low", "high"))
            ax.errorbar(mean, i, xerr=[[max(0, mean - low)], [max(0, high - mean)]],
                        fmt="o", color=INK, markersize=3, capsize=2, linewidth=0.8,
                        capthick=0.8)
        ax.set_title(title, loc="left", pad=9)
        ax.set_yticks(range(3), ("Uniform", "Owner", "Targeted") if metric == "recovered" else [])
        ax.set_ylim(2.5, -0.5)
        ax.set_xlabel("Affected lineages (%)" if metric == "recovered" else "Share ($10^{-3}$%)\nExpanded scale")
        if metric == "recovered":
            ax.set_xlim(0, 100)
            ax.set_xticks([0, 25, 50, 75, 100])
        else:
            high = max(100000 * float(lookup[(m, "0.90")]["allocation_gap_ci95_high"]) for m in mechanisms)
            ax.set_xlim(-0.2, high * 1.25)
            ax.tick_params(axis="x", labelsize=7.5)
            ax.locator_params(axis="x", nbins=3)
        clean_axis(ax, grid=None)
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)
    figure.subplots_adjust(left=0.12, right=0.98, bottom=0.18, top=0.87)
    save(figure, "fse_alert_losses")


def write_table(name, columns, header, lines):
    body = [f"\\begin{{tabular}}{{{columns}}}", r"\toprule", header + r" \\", r"\midrule"]
    body += lines + [r"\bottomrule", r"\end{tabular}"]
    (TABLES / f"{name}.tex").write_text("\n".join(body) + "\n", encoding="utf-8")


def tables():
    structure = read_rows(ROOT / "results/structure_by_event.csv")
    lines = []
    for row in structure:
        values = [event_label(row["event"])] + [f"{int(row[k]):,}" for k in
                  ("candidate_count", "affected_targets", "multi_ancestor_targets", "largest_component")]
        if row["event"] == "0507":
            values = [f"\\textbf{{{v}}}" for v in values]
        lines.append(" & ".join(values) + r" \\")
    write_table("fse_population", "lrrrr", "Event & Candidates & Targets & Multi-ancestor & Max component", lines)
    summary = read_rows(ROOT / "results/summary.csv")
    lookup = {(r["budget_fraction"], r["method"]): r for r in summary}
    methods = ("factor_hybrid", "bundle_greedy", "impact", "peeling", "random")
    lines = []
    for quota in sorted({r["budget_fraction"] for r in summary}, key=float):
        label = f"{100*float(quota):.0f}\\%"
        if quota == "0.1000":
            label = r"\textbf{" + label + "}"
        lines.append(label + " & " + " & ".join(
            f'{100*float(lookup[(quota, m)]["mean_recovered_fraction"]):.1f}' for m in methods) + r" \\")
    write_table("fse_outcomes", "rrrrrr", "Quota & Exact (ref.) & Bundle & Impact & Peeling & Random", lines)

    cases = read_rows(ROOT / "results/fse_escalation_cases.csv")
    stages = read_rows(ROOT / "results/complete_certificate_summary.csv")
    labels = {"bundle_root": "Bundle + root", "exact_root": "MILP + root", "branch_charge": "MILP + branch"}
    lines = []
    for row in stages:
        improved = sum(int(c["exact_value"]) > int(c["bundle_value"]) for c in cases if c["proof_stage"] == row["proof_stage"])
        lines.append(f'{labels[row["proof_stage"]]} & {row["event_budget_pairs"]} & {improved} & '
                     f'{row["total_nodes"]} & {int(row["total_proof_bytes"]):,}' + r" \\")
    total_improved = sum(int(c["exact_value"]) > int(c["bundle_value"]) for c in cases)
    total_pairs = sum(int(r["event_budget_pairs"]) for r in stages)
    total_nodes = sum(int(r["total_nodes"]) for r in stages)
    total_bytes = sum(int(r["total_proof_bytes"]) for r in stages)
    lines += [r"\midrule", f"Total & {total_pairs} & {total_improved} & {total_nodes} & {total_bytes:,}" + r" \\"]
    assert sum(int(r["event_budget_pairs"]) for r in stages) == 80
    assert sum(int(r["total_nodes"]) for r in stages) == 84
    assert sum(int(r["total_proof_bytes"]) for r in stages) == 27032
    write_table("fse_proof_overview", "lrrrr", "Closure stage & Pairs & Improved & Nodes & Proof bytes", lines)
    lines = []
    for row in cases:
        values = [event_label(row["event"]), f'{100*float(row["budget_fraction"]):.0f}\\%',
                  row["budget"], row["bundle_value"], row["root_integer_upper"], row["exact_value"],
                  "Quality" if int(row["exact_value"]) > int(row["bundle_value"]) else "Proof",
                  "Branch" if row["proof_stage"] == "branch_charge" else "Root"]
        lines.append(" & ".join(values) + r" \\")
    write_table("fse_cases", "lrrrrrll", "Event & Quota & $B$ & Bundle & Root UB & Exact & Gap & Closure", lines)
    _, summary_path, methods = runtime_sources()
    runtime = read_rows(summary_path)
    names = {method: name for method, name, _, _ in methods}
    lines = [names[r["method"]] + " & " + ("Yes" if r["method"] in {"certify_or_escalate", "milp_then_certify"} else "No") + " & " +
             " & ".join(f'{float(r[k]):.2f}' for k in ("median_ms", "p95_ms", "maximum_ms")) + r" \\" for r in runtime]
    write_table("fse_runtime_cost", "lcrrr", "Method & Indep. proof & Median & P95 & Max", lines)


def main():
    configure_deterministic_pdf()
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"],
                         "font.size": 8.5, "axes.labelsize": 8.5, "axes.titlesize": 8.5,
                         "xtick.labelsize": 8, "ytick.labelsize": 8,
                         "pdf.fonttype": 42, "ps.fonttype": 42, "hatch.linewidth": 0.35})
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    paired_gains()
    runtime_distribution()
    alert_losses()
    tables()


if __name__ == "__main__":
    main()
