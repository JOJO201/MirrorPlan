# Reproduction Guide

This anonymous release contains code, tests, frozen protocols, numeric
experiment outputs, and integer proof files. It contains no Git history,
author metadata, original upstream CSVs, model weights, or manuscript PDF.

## Tier 1: Released-File and Numeric Audit

From the repository root:

```bash
python3 scripts/verify_artifact.py --root .
```

This standard-library audit checks the release manifest, source records,
protocol consistency, seed and repetition coverage, solver-objective
agreements, loss identities, and recorded proof metadata. It does not
semantically check a proof without its encoded instance.

The release contains these retained raw tables:

| Table in `results/raw/` | Rows | Purpose |
|---|---:|---|
| `main_runs.csv` | 4,400 | Primary method and random-seed comparison |
| `alert_recall_runs.csv` | 6,400 | Initial incomplete-alert sensitivity |
| `runtime_runs.csv` | 1,120 | Original exact-solver timings |
| `core_extension_runs.csv` | 1,680 | Exact structural decomposition timings |
| `alert_stress_runs.csv` | 12,864 | Three incomplete-alert mechanisms |
| `certificate_runs.csv` | 80 | Root proof analysis |
| `complete_certificate_runs.csv` | 80 | Complete proof closure |
| `gap_extension_runs.csv` | 64,320 | Exact loss decomposition |
| `fse_decision_runtime.csv` | 1,680 | Earlier decision-path timing batch |
| `fse_instance_load_runtime.csv` | 112 | Separate instance-loading timings |
| `matched_certification_runtime.csv` | 2,240 | Four-method matched timing batch |

`results/mechanism_runs.csv` also retains 80 mechanism-ablation rows.
Later certification, simulation, and timing extensions retain their post-hoc
status in the corresponding protocols.

## Tier 2: Analysis and Figure Reproduction

```bash
bash scripts/reproduce_analysis.sh
```

This installs the Python dependencies and regenerates current FSE analyses,
plots, and LaTeX table fragments from released numeric outputs. It requires
no LaTeX installation and performs no historical data download or optimization
rerun. The current timing display uses only
the four-method matched batch. The static workflow exports and editable
PowerPoint are retained; presentation software is not required for numeric
reproduction. Manuscript sources, authoring-runtime scripts, review notes,
and previous submission packages are intentionally omitted.

These are the individual entrypoints for the latest timing and displays:

```bash
.venv/bin/python scripts/run_fse_revision.py --analysis-only --retained-cases
.venv/bin/python scripts/run_matched_certification.py --analysis-only
.venv/bin/python scripts/make_fse_visuals.py
```

Run the released-file audit before regenerating outputs. Regeneration or
local edits can change files covered by the original release manifest; the
frozen raw results and protocols should remain unchanged.

The earlier primary and extension analyses are also provided. Their legacy
plots use LaTeX text rendering. With a working LaTeX installation and its
Matplotlib text-rendering dependencies, opt into the complete older analysis:

```bash
MIRRORPLAN_FULL_ANALYSIS=1 bash scripts/reproduce_analysis.sh
```

The default current-figure workflow uses retained primary and extension
summaries; the optional full analysis recomputes those earlier summaries too.

## Tier 3: Source Reconstruction and Semantic Proof Checking

The full build downloads approximately 1.5 GB of public historical CSV
snapshots at the pinned source revision. It does not download model weights.
Source data, derived instances, and repository-level selections are ignored
by Git and must not be added to the anonymous release.

```bash
.venv/bin/python scripts/build_instances.py --discard-relations
.venv/bin/python scripts/verify_charge_certificates.py
.venv/bin/python scripts/verify_complete_certificates.py
```

The last command independently reconstructs residual branch problems from
the instances and checks all 80 complete proofs without numerical solving.
For a smaller download/parser check, use:

```bash
.venv/bin/python scripts/build_instances.py --events 0319 0416 --discard-relations
```

This builds only two events. It does not enable all-event proof checking.

## Fresh Experiment Runs

For a clean experiment rerun, use a separate checkout. Keep the released
results available as a reference rather than mixing new timings with them.
After rebuilding all instances, the main and extension entrypoints are:

```bash
.venv/bin/python scripts/run_experiments.py --protocol protocols/main.yaml
.venv/bin/python scripts/benchmark_runtime.py --protocol protocols/main.yaml
.venv/bin/python scripts/run_alert_recall.py
.venv/bin/python scripts/run_core_extension.py
.venv/bin/python scripts/run_alert_stress.py
.venv/bin/python scripts/run_certificate_extension.py
.venv/bin/python scripts/run_complete_certificate_extension.py
.venv/bin/python scripts/run_gap_extension.py --workers 4
.venv/bin/python scripts/analyze_mechanism.py
```

The latest timing command is `scripts/run_matched_certification.py`. It
refuses to overwrite its retained timing file. To measure afresh, first move
that file out of the separate experiment checkout, then run:

```bash
env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python scripts/run_matched_certification.py
```

Both certified methods include proposal generation, quantization, internal
consistency checks, solver work, and final integer audit. Imports, loading,
network access, source-graph construction, proof serialization, and additional
validation rechecks are excluded. Pair medians summarize seven repetitions
after one warmup. Original measurements used an 18 GB Apple M3 Pro and one
numerical thread. Runtime values are hardware-dependent; objective values
and checked proof conclusions should agree.

## Redistribution Boundary

The pinned source repository had no repository-level license. Its CSVs,
repository-identifying derived instances, and selection lists are excluded.
Owner labels in two aggregate structural summaries are redacted without
changing any numeric values. See `THIRD_PARTY.md` and `docs/data_audit.md`.
