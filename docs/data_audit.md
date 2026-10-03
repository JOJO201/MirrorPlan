# Data Audit

## Source

- Artifact: `MSC-empirical/msc-empirical`
- Pinned revision: `0e719b8587e30f464f2e204127e844833efbe965`
- Upstream study: *A First Look at Model Supply Chain: From the Risk
  Perspective* (ICSE 2026).
- Observation window used here: 16 transitions from 2025-03-12 through
  2025-07-02.

The builder downloads the pre-event relationship snapshot and the corresponding
weekly deletion CSV for each transition. Source URLs and byte counts are
recorded in `data/source_manifest.json`.

## Preserved fields

- Relationship snapshot: `Model ID`, `Type`, `Base Model`.
- Deletion file: `Model ID` plus upstream labels retained in the raw local copy.
- Merge rows may name multiple comma-separated bases; all are parsed as
  conjunctive declared inputs.

## License and redistribution

The pinned GitHub repository has no root `LICENSE` file and its GitHub license
endpoint returns 404 as checked on 2026-07-16. Public accessibility is not a
license grant. MirrorPlan therefore excludes upstream raw files from versioned
and packaged artifacts. The shareable package also excludes compact instances
and selected repository sets because they retain upstream identifiers.
Reproduction scripts download the inputs directly from the pinned source and
validate them against the recorded source metadata. Publication or
redistribution should be revisited if the upstream authors add a license or
grant permission.

## Semantic limitations

The relation is self-declared Hugging Face metadata. It may be incomplete,
incorrect, or missing. Deletion is inferred from consecutive snapshots and may
include temporary unavailability or renaming. A deleted base can break
provenance without making a derived repository unusable. Accordingly, the
outcome is complete declared lineage, not runtime availability.

The archived model listings omit file-level size metadata, so a storage-byte
budget cannot be reconstructed for deleted repositories. The main benchmark
uses a cardinality quota and reports that limitation prominently.
