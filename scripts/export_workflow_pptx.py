#!/usr/bin/env python3
"""Export the editable PowerPoint figure with a caller-supplied LibreOffice."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--soffice", required=True, type=Path)
    parser.add_argument("--ghostscript", default=shutil.which("gs"))
    parser.add_argument("--pptx", type=Path, default=ROOT / "results/figures/fse_workflow_editable.pptx")
    args = parser.parse_args()
    if not args.ghostscript:
        parser.error("Ghostscript is required to normalize the vector export to PDF 1.5.")
    with tempfile.TemporaryDirectory(prefix="workflow-export-") as temp:
        subprocess.run([str(args.soffice), "--headless", "--convert-to", "pdf",
                        "--outdir", temp, str(args.pptx.resolve())], check=True)
        generated = Path(temp) / (args.pptx.stem + ".pdf")
        normalized = Path(temp) / "workflow-pdf15.pdf"
        subprocess.run([str(args.ghostscript), "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE",
                        "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
                        f"-sOutputFile={normalized}", str(generated)], check=True)
        with pymupdf.open(normalized) as document:
            assert len(document) == 1 and not document[0].get_images()
            document.set_metadata({"title": "Retrospective construction and independent audit",
                                   "author": "", "creator": "", "producer": "",
                                   "creationDate": "", "modDate": ""})
            output = ROOT / "results/figures/fse_workflow"
            document.save(output.with_suffix(".pdf"), garbage=4, deflate=True, no_new_id=True)
            document[0].get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5)).save(output.with_suffix(".png"))
            output.with_suffix(".svg").write_text(document[0].get_svg_image(text_as_path=False), encoding="utf-8")
            print(f"Exported editable shapes to {output}.pdf/.svg/.png")


if __name__ == "__main__":
    main()
