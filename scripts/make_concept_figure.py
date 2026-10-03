#!/usr/bin/env python3
"""Explain a synthetic BLP counterexample and its closing charge witness."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Rectangle

from deterministic_plots import configure_deterministic_pdf
from make_fse_visuals import save


INK, GRAY, LIGHT = "#222222", "#737373", "#D4D4D4"
CANDIDATES = ("a", "b", "x", "y", "p_1", "p_2", "p_3", "q_1", "q_2", "q_3")
GROUPS = (("a", "b", 2),) + tuple(
    (parent, f"{prefix}_{i}", 1)
    for parent, prefix in (("x", "p"), ("y", "q")) for i in range(1, 4)
)
CHARGES = ((1, 1),) + ((0, 1),) * 6
POSITIONS = {"a": (54, 90), "b": (116, 90),
             "x": (43, 61), "y": (129, 61)}
for center, prefix in ((43, "p"), (129, "q")):
    for i, offset in enumerate((-25, 0, 25), 1):
        POSITIONS[f"{prefix}_{i}"] = (center + offset, 30)


def completed_groups(selected):
    selected = set(selected)
    return tuple(g for g in GROUPS if set(g[:2]) <= selected)


def value(selected):
    return sum(g[2] for g in completed_groups(selected))


def impact_scores():
    return {u: sum(w for a, b, w in GROUPS if u in (a, b)) for u in CANDIDATES}


def candidate_loads():
    loads = dict.fromkeys(CANDIDATES, 0)
    for (a, b, weight), (qa, qb) in zip(GROUPS, CHARGES, strict=True):
        assert qa >= 0 and qb >= 0 and qa + qb == weight
        loads[a] += qa
        loads[b] += qb
    return loads


def canvas_panel(figure, position, title):
    ax = figure.add_axes(position)
    ax.set_xlim(0, 172)
    ax.set_ylim(0, 115)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.text(0, 122, title, fontsize=9, va="bottom", color=INK)
    return ax


def node(ax, label, x, y, *, color=GRAY, selected=False):
    ax.add_patch(Circle((x, y), 7.3, edgecolor=color, linewidth=0.8,
                        facecolor=color if selected else "white", zorder=3))
    ax.text(x, y, f"${label}$", fontsize=8.5, ha="center", va="center",
            color="white" if selected else INK, zorder=4)


def instance_panel(ax):
    for a, b, weight in GROUPS:
        xa, ya = POSITIONS[a]
        xb, yb = POSITIONS[b]
        ax.plot((xa, xb), (ya, yb), color=INK if weight == 2 else GRAY,
                linewidth=1.2 if weight == 2 else 0.7, zorder=1)
    for u, (x, y) in POSITIONS.items():
        node(ax, u, x, y)
    ax.text(85, 104, "$w_e=2$", fontsize=8.5, ha="center", color=INK)
    ax.text(166, 109, "$B=2$", fontsize=8.5, ha="right", color=INK)
    ax.text(86, 12, "Six spokes: $w_e=1$ each", fontsize=8, ha="center", color=GRAY)
    ax.text(86, 0, "Edge = both endpoints required", fontsize=8, ha="center", color=INK)


def comparison_panel(ax):
    scores = impact_scores()
    ax.text(0, 109, "Impact: rank by $I(u)$", fontsize=8.5, color=INK)
    for label, score, y, color in (
        ("$x,y$", scores["x"], 96, INK),
        ("$a,b$", scores["a"], 84, GRAY),
        ("$p_i,q_i$", scores["p_1"], 72, GRAY),
    ):
        ax.text(0, y, label, fontsize=8, va="center")
        ax.add_patch(Rectangle((43, y - 3), 13 * score, 6, facecolor=color, edgecolor="none"))
        ax.text(88, y, str(score), fontsize=8, ha="center", va="center", color=color)
    for label, x in (("x", 120), ("y", 151)):
        node(ax, label, x, 91, color=INK, selected=True)
    ax.text(136, 68, f"$f(\\{{x,y\\}})={value(('x', 'y'))}$", ha="center", fontsize=9,
            color=INK)
    ax.plot((0, 172), (58, 58), color=LIGHT, linewidth=0.65)
    ax.text(0, 48, "Bundle: gain / cost", fontsize=8.5, color=INK)
    for label, ratio, y, color in (("$\\{a,b\\}$", GROUPS[0][2] / 2, 35, INK),
                                  ("Spoke", GROUPS[1][2] / 2, 22, GRAY)):
        ax.text(0, y, label, fontsize=8, va="center")
        ax.add_patch(Rectangle((43, y - 3), 39 * ratio, 6, facecolor=color, edgecolor="none"))
        ax.text(88, y, f"{ratio:g}", fontsize=8, ha="center", va="center", color=color)
    ax.plot((120, 151), (33, 33), color=INK, linewidth=1.2, zorder=1)
    for label, x in (("a", 120), ("b", 151)):
        node(ax, label, x, 33, color=INK, selected=True)
    ax.text(136, 10, f"$f(\\{{a,b\\}})={value(('a', 'b'))}$", ha="center", fontsize=9,
            color=INK)


def charge_panel(ax):
    ax.text(0, 107, "Group $e$", fontsize=8, color=GRAY)
    ax.text(57, 107, "$w_e$", fontsize=8, ha="center", color=GRAY)
    ax.text(123, 107, "Endpoint charges", fontsize=8, ha="center", color=GRAY)
    ax.plot((0, 172), (101, 101), color=INK, linewidth=0.7)
    # The indexed rows each represent three distinct groups, not one weight-3 group.
    patterns = ((0, ("a", "b")), (1, ("x", "p_i")), (4, ("y", "q_i")))
    for index, (group_index, (a_label, b_label)) in enumerate(patterns):
        weight = GROUPS[group_index][2]
        y = 85 - index * 24
        qa, qb = CHARGES[group_index]
        ax.text(0, y, f"$\\{{{a_label},{b_label}\\}}$", fontsize=8.5, va="center")
        ax.text(57, y, str(weight), fontsize=8.5, ha="center", va="center")
        for label, charge, x in ((a_label, qa, 99), (b_label, qb, 150)):
            ax.text(x, y, f"${label}: {charge}$", fontsize=8.5, ha="center", va="center",
                    color=INK)
        ax.plot((0, 172), (y - 13, y - 13), color=LIGHT, linewidth=0.55)
    ax.text(0, 15, "$i=1,2,3$ in each indexed row", fontsize=8, color=GRAY)
    ax.text(86, 0, "$\\sum_{u\\in e}\\alpha_{eu}=w_e$ for every group", fontsize=8.5,
            ha="center", color=INK)


def load_panel(figure, position):
    ax = figure.add_axes(position)
    ax.set_xlim(-0.95, 9.65)
    ax.set_ylim(-1.20, 1.65)
    ax.axis("off")
    ax.text(-0.95, 1.82, "(d) A matching optimality bound", fontsize=9,
            color=INK, va="bottom")
    ax.text(-0.95, 1.41, "Candidate loads $\\ell_u$", fontsize=8, color=GRAY)
    loads = candidate_loads()
    bars = ax.bar(range(10), [loads[u] for u in CANDIDATES], width=0.65,
                  color=[INK if u in ("a", "b") else GRAY for u in CANDIDATES],
                  edgecolor="white", linewidth=0.5, zorder=2)
    for u, bar in zip(CANDIDATES, bars, strict=True):
        bar.set_gid(f"load:{u}")
    ax.plot((-0.65, 9.5), (0, 0), color=GRAY, linewidth=0.7)
    ax.plot((-0.65, -0.65), (0, 1.05), color=GRAY, linewidth=0.7)
    ax.plot((-0.65, 9.5), (1, 1), color=LIGHT, linewidth=0.6, zorder=0)
    for y in (0, 1):
        ax.text(-0.82, y, str(y), fontsize=8, ha="right", va="center", color=GRAY)
    ax.scatter((2, 3), (0, 0), s=12, facecolor="white", edgecolor=GRAY,
               linewidth=0.7, zorder=4)
    for x, u in enumerate(CANDIDATES):
        ax.text(x, -0.17, f"${u}$", fontsize=8, ha="center", va="top")
    bound = sum(sorted(loads.values(), reverse=True)[:2])
    ax.text(4.3, -0.62, f"$U_2=1+1={bound}$  (two largest loads)", fontsize=8.5,
            ha="center", color=INK)
    ax.text(4.3, -1.04, "$f(\\{a,b\\})=2\\;\\leq\\;\\mathrm{OPT}\\;\\leq\\;U_2=2$",
            fontsize=9, ha="center", color=INK)
    return ax


def draw_figure():
    configure_deterministic_pdf()
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5,
                         "mathtext.fontset": "dejavusans", "text.usetex": False,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    figure = plt.figure(figsize=(5.45, 3.75))
    top_left = canvas_panel(figure, (0.035, 0.545, 0.445, 0.375),
                            "(a) Conjunctive requirements")
    top_right = canvas_panel(figure, (0.545, 0.545, 0.42, 0.375),
                             "(b) Two feasible selections")
    lower_left = canvas_panel(figure, (0.035, 0.06, 0.445, 0.385),
                              "(c) Conserved group charges")
    instance_panel(top_left)
    comparison_panel(top_right)
    charge_panel(lower_left)
    load_panel(figure, (0.555, 0.06, 0.41, 0.385))
    figure.add_artist(Line2D((0.035, 0.965), (0.515, 0.515), transform=figure.transFigure,
                             color=LIGHT, linewidth=0.65))
    return figure


def main() -> None:
    save(draw_figure(), "running_example")


if __name__ == "__main__":
    main()
