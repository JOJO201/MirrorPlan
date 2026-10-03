import csv
import importlib
import statistics
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
ROOT = Path(__file__).parents[1]


def rows(name):
    with (ROOT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_paired_display_keeps_all_ties_and_events():
    values = {(r["event"], r["method"]): int(r["value"])
              for r in rows("results/raw/main_runs.csv")
              if r["budget_fraction"] == "0.1000" and r["method"] != "random"}
    events = {e for e, _ in values}
    assert len(events) == 16
    assert sum(values[(e, "factor_hybrid")] > values[(e, "impact")] for e in events) == 6
    bundle_gains = {e: values[(e, "factor_hybrid")] - values[(e, "bundle_greedy")] for e in events}
    assert {e: g for e, g in bundle_gains.items() if g} == {"0507": 1}


def test_runtime_cdf_contains_even_the_fastest_bundle_pairs(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    visuals = importlib.import_module("make_fse_visuals")
    captured = []
    monkeypatch.setattr(visuals, "save", lambda figure, name: captured.append(figure))
    visuals.runtime_distribution()
    ax = captured[0].axes[0]
    grouped = defaultdict(list)
    source, _, methods = visuals.runtime_sources()
    for r in rows(str(source.relative_to(ROOT))):
        grouped[(r["event"], r["budget_fraction"], r["method"])].append(float(r["decision_seconds"]) * 1000)
    assert len(grouped) == 80 * len(methods) and all(len(v) == 7 for v in grouped.values())
    medians = [statistics.median(v) for v in grouped.values()]
    assert ax.get_xlim()[0] < min(medians) <= max(medians) < ax.get_xlim()[1]
    assert len(ax.lines) == len(methods)
    assert all(len(line.get_xdata()) == 82 for line in ax.lines)
    assert all(line.get_ydata()[0] == 0 and line.get_ydata()[-1] == 1 for line in ax.lines)
    plt.close(captured[0])


def test_proof_display_distinguishes_quality_and_proof_gaps():
    cases = rows("results/fse_escalation_cases.csv")
    assert len(cases) == 4
    improved = [r for r in cases if int(r["exact_value"]) > int(r["bundle_value"])]
    unchanged = [r for r in cases if int(r["exact_value"]) == int(r["bundle_value"])]
    assert len(improved) == len(unchanged) == 2
    assert all(r["proof_stage"] == "exact_root" for r in improved)
    assert all(r["proof_stage"] == "branch_charge" for r in unchanged)
    assert all(int(r["added_candidates"]) == int(r["removed_candidates"]) == 0 for r in unchanged)


def test_workflow_edges_cross_into_checker_before_acceptance():
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    with ZipFile(ROOT / "results/figures/fse_workflow_editable.pptx") as archive:
        graph = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
    names = {s.find("p:nvSpPr/p:cNvPr", ns).get("id"):
             s.find("p:nvSpPr/p:cNvPr", ns).get("name") for s in graph.findall(".//p:sp", ns)}
    edges, arrow_pairs = set(), set()
    for edge in graph.findall(".//p:cxnSp", ns):
        start = edge.find("p:nvCxnSpPr/p:cNvCxnSpPr/a:stCxn", ns)
        end = edge.find("p:nvCxnSpPr/p:cNvCxnSpPr/a:endCxn", ns)
        arrow = edge.find("p:spPr/a:ln/a:tailEnd", ns)
        assert arrow is None or arrow.get("type") in ("triangle", "none")
        assert edge.find("p:spPr/a:ln/a:headEnd", ns) is None
        pair = (names[start.get("id")], names[end.get("id")])
        edges.add(pair)
        if arrow is not None and arrow.get("type") == "triangle":
            arrow_pairs.add(pair)
    assert {("absence-source", "absence-turn"), ("absence-turn", "absence-input"),
            ("absence-input", "construct"), ("quota-source", "quota-turn"),
            ("quota-turn", "quota-down"), ("quota-down", "quota-input"),
            ("original-instance-origin", "original-instance-rise"),
            ("original-instance-rise", "original-instance-turn"),
            ("original-instance-turn", "checker"),
            ("checker", "feedback-right"), ("feedback-right", "feedback-left"),
            ("feedback-left", "generate"), ("reject-origin", "reject-turn"),
            ("reject-turn", "reject-top"), ("reject-top", "rejected")} <= edges
    assert {("absence-input", "construct"), ("quota-down", "quota-input"),
            ("original-instance-turn", "checker"), ("feedback-left", "generate"),
            ("reject-top", "rejected")} <= arrow_pairs
    shapes = {s.find("p:nvSpPr/p:cNvPr", ns).get("name"): s
              for s in graph.findall(".//p:sp", ns)}

    def bounds(name):
        transform = shapes[name].find("p:spPr/a:xfrm", ns)
        offset, size = transform.find("a:off", ns), transform.find("a:ext", ns)
        return tuple(int(value) for value in
                     (offset.get("x"), offset.get("y"), size.get("cx"), size.get("cy")))

    main_arrows = {
        "source-to-construct": ("lineage-back", "construct"),
        "construct-to-instance": ("construct", "instance"),
        "instance-to-generate": ("instance", "generate"),
        "generation-to-plan": ("generate", "plan"),
        "generation-to-proof": ("generate", "proof"),
        "plan-to-checker": ("plan", "checker"),
        "proof-to-checker": ("proof", "checker"),
        "closed-to-output": ("checker", "accepted"),
    }
    for name, (source, target) in main_arrows.items():
        x, y, width, height = bounds(name)
        source_x, _, source_width, _ = bounds(source)
        target_x, _, _, _ = bounds(target)
        assert abs(x - source_x - source_width) <= 2
        assert abs(x + width - target_x) <= 2
        assert shapes[name].find("p:spPr/a:custGeom", ns) is not None
        assert shapes[name].find("p:spPr/a:xfrm", ns).get("flipH") not in {"1", "true"}
    plan, proof = bounds("plan"), bounds("proof")
    assert plan[1] + plan[3] < proof[1]
    instance, origin = bounds("instance"), bounds("original-instance-origin")
    assert instance[0] <= origin[0] <= instance[0] + instance[2]
    assert origin[1] == instance[1]
    checker, reject_origin = bounds("checker"), bounds("reject-origin")
    assert reject_origin[0] == checker[0] + checker[2] and reject_origin[1] == checker[1]
    titles = ["".join(shapes[f"stage-{i}-title"].itertext()).strip() for i in range(1, 5)]
    assert titles == ["Encode", "Plan", "Integer audit", "Return"]
    assert len(shapes) == 76 and len(graph.findall(".//p:cxnSp", ns)) == 17
    assert len(graph.findall(".//a:t", ns)) == 35 and not graph.findall(".//p:pic", ns)


def test_runtime_summary_is_descriptive_not_a_bootstrap_interval(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    visuals = importlib.import_module("make_fse_visuals")
    captured = []
    monkeypatch.setattr(visuals, "save", lambda figure, name: captured.append(figure))
    visuals.runtime_distribution()
    figure = captured[0]
    assert len(figure.axes) == 2
    assert figure.axes[0].get_xlim() == figure.axes[1].get_xlim()
    _, summary_path, methods = visuals.runtime_sources()
    summary = rows(str(summary_path.relative_to(ROOT)))
    for i, (method, _, _, _) in enumerate(methods):
        row = next(r for r in summary if r["method"] == method)
        points = figure.axes[1].collections[4*i + 1:4*i + 3]
        assert abs(float(points[0].get_offsets()[0, 0]) - float(row["median_ms"])) < 1e-8
        assert abs(float(points[1].get_offsets()[0, 0]) - float(row["p95_ms"])) < 1e-8
        maximum = figure.axes[1].collections[4*i + 3].get_offsets()[0, 0]
        assert abs(float(maximum) - float(row["maximum_ms"])) < 1e-8
        segment = figure.axes[1].collections[4*i].get_segments()[0]
        assert abs(segment[0, 0] - float(row["median_ms"])) < 1e-8
        assert abs(segment[1, 0] - float(row["maximum_ms"])) < 1e-8
    plt.close(figure)


def test_paired_baselines_share_a_scale_before_bundle_zoom(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    visuals = importlib.import_module("make_fse_visuals")
    captured = []
    monkeypatch.setattr(visuals, "save", lambda figure, name: captured.append(figure))
    visuals.paired_gains()
    comparison, zoom = captured[0].axes
    assert comparison.get_xlim()[1] > 15
    assert len(comparison.collections) == 4
    assert all(len(comparison.collections[i].get_offsets()) == 16 for i in (1, 3))
    assert "Expanded scale" in zoom.get_xlabel()
    plt.close(captured[0])


def test_synthetic_graph_example_and_closing_charge(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    example = importlib.import_module("make_concept_figure")
    candidates = example.CANDIDATES
    assert len(candidates) == 10 and len(example.GROUPS) == 7
    assert set(example.POSITIONS) == set(candidates)
    assert example.value(("x", "y")) == 0
    assert example.value(("a", "b")) == max(
        example.value(s) for s in combinations(candidates, 2)) == 2
    assert example.impact_scores() == {
        c: 3 if c in ("x", "y") else 2 if c in ("a", "b") else 1
        for c in candidates}
    assert [weight / 2 for _, _, weight in example.GROUPS] == [1] + [0.5] * 6
    loads = example.candidate_loads()
    assert loads == {c: 0 if c in ("x", "y") else 1 for c in candidates}
    assert sum(loads.values()) == 8
    assert all(qa + qb == weight and qa >= 0 and qb >= 0
               for (_, _, weight), (qa, qb) in zip(example.GROUPS, example.CHARGES, strict=True))
    assert sum(sorted(loads.values(), reverse=True)[:2]) == 2


def test_synthetic_figure_load_bars_match_the_actual_witness(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    example = importlib.import_module("make_concept_figure")
    figure = example.draw_figure()
    assert len(figure.axes) == 4
    graph, comparison, charges, loads = figure.axes
    assert len(graph.patches) == 10 and len(graph.lines) == 7
    assert len(comparison.patches) == 9  # Five score bars and four selected nodes.
    assert not charges.patches
    displayed_charges = {text.get_text() for text in charges.texts}
    assert {"$a: 1$", "$b: 1$", "$x: 0$", "$p_i: 1$", "$y: 0$", "$q_i: 1$"} <= displayed_charges
    actual = {bar.get_gid().removeprefix("load:"): bar.get_height()
              for bar in loads.containers[0]}
    assert actual == example.candidate_loads()
    assert all(bar.get_hatch() is None for bar in loads.containers[0])
    assert [bar.get_facecolor() for bar in loads.containers[0]][:2] == [to_rgba(example.INK)] * 2
    assert all(bar.get_facecolor() == to_rgba(example.GRAY) for bar in loads.containers[0][2:])
    colors = []
    for ax in figure.axes:
        colors.extend(to_rgba(text.get_color()) for text in ax.texts)
        colors.extend(to_rgba(line.get_color()) for line in ax.lines)
        for patch in ax.patches:
            colors.extend((patch.get_facecolor(), patch.get_edgecolor()))
        for collection in ax.collections:
            colors.extend(collection.get_facecolors())
            colors.extend(collection.get_edgecolors())
    assert all(abs(c[0] - c[1]) < 1e-8 and abs(c[1] - c[2]) < 1e-8 for c in colors)
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    labels = [text for ax in figure.axes for text in ax.texts]
    boxes = [text.get_window_extent(renderer) for text in labels]
    assert all(figure.bbox.contains(box.x0, box.y0) and
               figure.bbox.contains(box.x1, box.y1) for box in boxes)
    assert all(not a.overlaps(b) for a, b in combinations(boxes, 2))
    plt.close(figure)


def test_allocation_display_rescales_retained_intervals_only(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    visuals = importlib.import_module("make_fse_visuals")
    captured = []
    monkeypatch.setattr(visuals, "save", lambda figure, name: captured.append(figure))
    visuals.alert_losses()
    ax = captured[0].axes[-1]
    lookup = {r["mechanism"]: r for r in rows("results/gap_decomposition_summary.csv")
              if r["budget_fraction"] == "0.1000" and r["alert_recall"] == "0.90"}
    assert "10^{-3}" in ax.get_xlabel() and "Expanded scale" in ax.get_xlabel()
    for container, mechanism in zip(ax.containers, ("uniform", "owner_clustered", "impact_targeted"), strict=True):
        row = lookup[mechanism]
        assert abs(container.lines[0].get_xdata()[0] - 100000 * float(row["mean_allocation_gap_fraction"])) < 1e-8
        segment = container.lines[2][0].get_segments()[0]
        assert abs(segment[0, 0] - 100000 * float(row["allocation_gap_ci95_low"])) < 1e-8
        assert abs(segment[1, 0] - 100000 * float(row["allocation_gap_ci95_high"])) < 1e-8
    plt.close(captured[0])


def test_minimal_displays_use_solid_grays_and_retain_loss_partitions(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    visuals = importlib.import_module("make_fse_visuals")
    captured = []
    monkeypatch.setattr(visuals, "save", lambda figure, name: captured.append(figure))
    with plt.rc_context({"font.size": 8.5, "axes.titlesize": 8.5}):
        visuals.paired_gains()
        visuals.runtime_distribution()
        visuals.alert_losses()
    for figure in captured:
        colors = []
        for ax in figure.axes:
            colors.extend(to_rgba(line.get_color()) for line in ax.lines)
            for collection in ax.collections:
                colors.extend(collection.get_facecolors())
                colors.extend(collection.get_edgecolors())
            for patch in ax.patches:
                assert not patch.get_hatch()
                colors.extend((patch.get_facecolor(), patch.get_edgecolor()))
        assert all(abs(c[0] - c[1]) < 1e-8 and abs(c[1] - c[2]) < 1e-8 for c in colors)
    _, _, methods = visuals.runtime_sources()
    assert {line.get_linestyle() for line in captured[1].axes[0].lines} == {style for _, _, _, style in methods}
    lookup = {(r["mechanism"], r["alert_recall"]): r
              for r in rows("results/gap_decomposition_summary.csv")
              if r["budget_fraction"] == "0.1000"}
    fields = ("mean_recovered_fraction", "mean_capacity_gap_fraction",
              "mean_alert_gap_fraction", "mean_allocation_gap_fraction")
    recalls = ("0.50", "0.70", "0.90", "1.00")
    for ax, mechanism in zip(captured[2].axes[:3],
                             ("uniform", "owner_clustered", "impact_targeted"), strict=True):
        for j, recall in enumerate(recalls):
            left = 0
            for container, field in zip(ax.containers, fields, strict=True):
                bar = container[j]
                expected = 100 * float(lookup[(mechanism, recall)][field])
                assert abs(bar.get_x() - left) < 1e-8
                assert abs(bar.get_width() - expected) < 1e-8
                left += expected
            assert abs(left - 100) < 1e-8
    for figure in captured:
        plt.close(figure)
