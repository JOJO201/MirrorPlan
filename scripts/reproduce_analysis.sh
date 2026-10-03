#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONHASHSEED=0
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export MPLBACKEND=Agg
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -f MANIFEST.sha256 ]]; then
  python3 scripts/verify_artifact.py --root .
fi

PYTHON="${MIRRORPLAN_PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  if [[ -n "${MIRRORPLAN_PYTHON:-}" ]]; then
    printf '%s\n' 'MIRRORPLAN_PYTHON must name an executable Python interpreter.' >&2
    exit 1
  fi
  python3 -m venv .venv
fi
if [[ "${MIRRORPLAN_SKIP_INSTALL:-0}" != 1 ]]; then
  "$PYTHON" -m pip install -e '.[dev]'
fi

"$PYTHON" -m pytest
if [[ "${MIRRORPLAN_FULL_ANALYSIS:-0}" == 1 ]]; then
  if ! command -v latex >/dev/null 2>&1; then
    printf '%s\n' 'Legacy plot regeneration requires a working LaTeX installation.' >&2
    exit 1
  fi
  "$PYTHON" scripts/analyze_results.py --root "$ROOT"
  "$PYTHON" scripts/analyze_robustness.py
  "$PYTHON" scripts/analyze_extensions.py
  "$PYTHON" scripts/analyze_structure.py
fi
"$PYTHON" scripts/make_concept_figure.py
"$PYTHON" scripts/make_paper_tables.py
"$PYTHON" scripts/run_fse_revision.py --analysis-only --retained-cases
"$PYTHON" scripts/run_matched_certification.py --analysis-only
"$PYTHON" scripts/make_fse_visuals.py
printf '%s\n' 'Analysis reproduction completed; no source download or optimization rerun.'
