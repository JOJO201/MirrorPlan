#!/usr/bin/env python3
"""Create the editable audit workflow; export through draw.io when requested."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).parents[1]
OUT = ROOT / "results/figures/fse_workflow_legacy"


def build_source():
    document = ET.Element("mxfile", host="app.diagrams.net")
    page = ET.SubElement(document, "diagram", id="fse-workflow", name="Audit workflow")
    model = ET.SubElement(page, "mxGraphModel", grid="1", gridSize="10", page="1",
                          pageScale="1", pageWidth="1000", pageHeight="660",
                          math="1", shadow="0")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    def node(key, label, x, y, w, h, *, fill="#FFFFFF", stroke="#55616A",
             text=False, bold=False, size=21, extra="", parent="1"):
        style = ("text;" if text else "rounded=0;") + (
            f"html=1;whiteSpace=wrap;fontFamily=Arial;fontSize={size};"
            f"fontColor=#222222;fillColor={'none' if text else fill};"
            f"strokeColor={'none' if text else stroke};strokeWidth=1.6;"
            "align=center;verticalAlign=middle;spacing=4;"
        ) + ("fontStyle=1;" if bold else "") + extra
        cell = ET.SubElement(root, "mxCell", id=key, value=label, style=style,
                             vertex="1", parent=parent)
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(w),
                      height=str(h), **{"as": "geometry"})

    def edge(key, source, target, points=(), *, ports="", arrow=True):
        style = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"
                 f"endArrow={'block' if arrow else 'none'};strokeColor=#55616A;"
                 "strokeWidth=1.8;jettySize=auto;") + ports
        cell = ET.SubElement(root, "mxCell", id=key, value="", style=style,
                             edge="1", parent="1", source=source, target=target)
        geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        if points:
            array = ET.SubElement(geometry, "Array", **{"as": "points"})
            for x, y in points:
                ET.SubElement(array, "mxPoint", x=str(x), y=str(y))

    node("panel-construction", "(a) Retrospective benchmark construction", 20, 10, 960, 30,
         text=True, bold=True, size=23, extra="align=left;")
    node("graph", "", 30, 60, 240, 100)
    node("graph-label", "Pre-event lineage", 40, 130, 220, 20, text=True, size=18)
    for key, x, y, fill in (("a", 80, 70, "#DCECF6"), ("b", 180, 70, "#DCECF6"),
                            ("v", 130, 100, "#E8ECEF")):
        node(f"graph-{key}", "", x, y, 20, 20, fill=fill, extra="ellipse;aspect=fixed;")
    node("absences", "Next-snapshot<br>observed absences", 350, 60, 240, 100, fill="#F7F8FA")
    node("instance", "Grouped requirements<br>Candidate set<br>Repository-count quota", 730, 60, 240, 100,
         fill="#F7F8FA", size=20)
    node("next-label", "Next<br>snapshot", 270, 60, 80, 40, text=True, size=18)
    node("replay-label", "Replay on<br>pre-event graph", 590, 60, 140, 40, text=True, size=18)
    node("oracle-note", "Future absences supply the candidates; no warning predictor is evaluated.",
         30, 170, 940, 30, text=True, size=20)
    node("panel-audit", "(b) Certify-or-escalate decision audit", 20, 210, 960, 30,
         text=True, bold=True, size=23, extra="align=left;")
    node("generator-header", "Untrusted generators", 30, 240, 260, 30, text=True, bold=True)
    node("checker-header", "Trusted integer checker", 400, 240, 260, 30, text=True, bold=True)
    node("output-header", "Accepted output", 780, 240, 190, 30, text=True, bold=True)
    generators = (
        ("bundle", "Bundle plan +<br>optimized root charges"),
        ("milp", "Global MILP candidate<br>Reuse root charges"),
        ("branch", "Residual branch generator<br>Include and exclude children"),
    )
    checks = (
        ("root-audit", "Integer root audit<br>Value and upper bound"),
        ("re-audit", "Integer re-audit<br>Same bound, new plan"),
        ("tree-audit", "Integer tree audit<br>Reconstruct residuals"),
    )
    for i, ((key, label), (audit, audit_label)) in enumerate(zip(generators, checks)):
        y = 280 + 130 * i
        node(key, label, 30, y, 260, 60, fill="#EDF4F9", stroke="#0072B2", size=20)
        node(audit, audit_label, 400, y, 260, 60, fill="#E7F3EF", stroke="#007B5A", size=20)
        node(f"accepted-{i}", "Accept plan<br>" + ("Root proof" if i < 2 else "Branch proof"),
             780, y, 190, 60, size=20)
        node(f"closed-label-{i}", "Closed" if i < 2 else "Tree closed", 660, y-10, 120, 30,
             text=True, size=18)
    for i in range(2):
        node(f"open-label-{i}", "Open bound", 350, 340 + 130 * i, 150, 20, text=True, size=18)
    node("reject-note", "Invalid or incomplete proofs are rejected; the checker imports no optimizer.",
         30, 620, 940, 25, text=True, size=19)
    edge("graph-a-v", "graph-a", "graph-v", arrow=False)
    edge("graph-b-v", "graph-b", "graph-v", arrow=False)
    edge("graph-absences", "graph", "absences")
    edge("absences-instance", "absences", "instance")
    for i, ((key, _), (audit, _)) in enumerate(zip(generators, checks)):
        edge(f"proof-{i}", key, audit)
        edge(f"accepted-edge-{i}", audit, f"accepted-{i}")
    for i, (source, target) in enumerate((("root-audit", "milp"), ("re-audit", "branch"))):
        y = 370 + 130 * i
        edge(f"escalate-{i}", source, target, ((530, y), (160, y)),
             ports="exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
    ET.indent(document, space="  ")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(document).write(OUT.with_suffix(".drawio"), encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-cli", type=Path, help="Optional draw.io Desktop executable")
    args = parser.parse_args()
    build_source()
    if args.export_cli:
        for extension in ("svg", "pdf", "png"):
            command = [str(args.export_cli), "--export", "--format", extension,
                       "--crop", "--border", "10", "--output", str(OUT.with_suffix(f".{extension}")),
                       str(OUT.with_suffix(".drawio"))]
            subprocess.run(command, check=True, timeout=120)
        # TeX Live 2020 accepts PDF 1.5; normalize the vector export, not the layout.
        ghostscript = shutil.which("gs")
        if ghostscript:
            temporary = OUT.with_suffix(".normalized.pdf")
            subprocess.run([ghostscript, "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                            "-dCompatibilityLevel=1.5", f"-sOutputFile={temporary}",
                            str(OUT.with_suffix(".pdf"))], check=True, timeout=120)
            temporary.replace(OUT.with_suffix(".pdf"))
    print(OUT.with_suffix(".drawio"))


if __name__ == "__main__":
    main()
