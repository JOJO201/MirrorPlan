# MirrorPlan

Anonymous replication package for **MirrorPlan: Auditable Preservation
Planning for Model Supply Chains**.

MirrorPlan selects repository bundles under a repository-count quota and
independently checks optimality with integer charge and branch proofs. Its
historical Hugging Face benchmark measures completion of declared ancestry,
not model execution or repository capture.

## Contents

- `src/mirrorplan/`: instance construction, baselines, exact solvers, and
  independent integer checkers.
- `scripts/`: data reconstruction, experiments, analysis, and verification.
- `protocols/`: frozen primary and post-hoc experiment definitions.
- `results/`: retained numeric rows, summaries, and 80 complete proofs.
- `tests/`: algorithm, data, proof, and display checks.
- `examples/`: a small runnable instance with no source-data download.
- `paper/generated/`: generated table fragments, not manuscript sources.
- `ARTIFACT.md`: detailed reproduction instructions and measurement scope.

## Install and Run

Use Python 3.11 or newer. The measured environment used Python 3.13.1.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python examples/audit_small_instance.py
```

`requirements-tested.txt` records the direct dependency versions used to
validate this package. To use those versions on a compatible environment:

```bash
.venv/bin/python -m pip install -r requirements-tested.txt
.venv/bin/python -m pip install -e '.[dev]'
```

The example prints the selected plan, its objective, and the independently
checked proof stage for heuristic-first and MILP-first planning.

## Reproduce Retained Results

The following commands do not download the historical snapshots or rerun
optimization experiments:

```bash
python3 scripts/verify_artifact.py --root .
bash scripts/reproduce_analysis.sh
```

The first checks the released files, frozen protocols, recorded proofs, and
numeric coverage using the Python standard library. The second installs the
dependencies, runs the tests, and regenerates the current FSE analyses,
table fragments, and figures from retained numeric outputs. This default
workflow does not require LaTeX or compile a manuscript.

Independent semantic checking of the historical proofs requires rebuilding
the corresponding instances; see `ARTIFACT.md`.

## Data and Results

The historical inputs are pinned to revision
`0e719b8587e30f464f2e204127e844833efbe965` of
[MSC-empirical/msc-empirical](https://github.com/MSC-empirical/msc-empirical).
Source URLs are recorded in `data/source_manifest.json`.

The package retains 16 events, 80 event-quota pairs, 4,400 primary result rows,
64,320 incomplete-alert simulation rows, and 2,240 matched-certification
timing rows. Bundle reaches 78 of 80 optima; the complete workflow independently
certifies all 80. Heuristic-first and MILP-first use the same certification
module. Their overall median decision times are 8.96 and 8.33 ms, respectively.
The latter comparison is descriptive and post-hoc, not a new primary study.

The pinned source revision had no repository-level license. Upstream CSVs,
identifier-bearing instances, and selected repository lists are not included.
Aggregate owner-name fields are redacted; their numeric statistics are retained.
The reconstruction scripts obtain source data directly from the upstream
repository. No model weights are downloaded.

## License

Original code and documentation are MIT licensed. Third-party data and
dependencies retain their own terms; see `LICENSE` and `THIRD_PARTY.md`.
