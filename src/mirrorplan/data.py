"""Pinned data access and parsers for the Model Supply Chain artifact."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PINNED_COMMIT = "0e719b8587e30f464f2e204127e844833efbe965"
RAW_ROOT = (
    "https://raw.githubusercontent.com/MSC-empirical/msc-empirical/"
    f"{PINNED_COMMIT}/data"
)

EVENT_PAIRS: tuple[tuple[str, str], ...] = (
    ("0312", "0319"),
    ("0319", "0326"),
    ("0326", "0402"),
    ("0402", "0409"),
    ("0409", "0416"),
    ("0416", "0423"),
    ("0423", "0430"),
    ("0430", "0507"),
    ("0507", "0514"),
    ("0514", "0521"),
    ("0521", "0528"),
    ("0528", "0604"),
    ("0604", "0611"),
    ("0611", "0618"),
    ("0618", "0625"),
    ("0625", "0702"),
)


@dataclass(frozen=True)
class DownloadRecord:
    relative_path: str
    url: str
    bytes: int
    sha256: str


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> DownloadRecord:
    """Download atomically and return an auditable content record."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "MirrorPlan/0.1 research artifact"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                with temporary.open("wb") as output:
                    while chunk := response.read(1 << 20):
                        output.write(chunk)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return DownloadRecord(
        relative_path=str(destination),
        url=url,
        bytes=destination.stat().st_size,
        sha256=sha256_file(destination),
    )


def source_paths(raw_dir: Path, snapshot: str, event: str) -> tuple[Path, Path]:
    relation = raw_dir / "model_relation" / f"batch_all_{snapshot}.csv"
    deleted = raw_dir / "deleted_models" / f"deleted_model_{event}.csv"
    return relation, deleted


def fetch_event(raw_dir: Path, snapshot: str, event: str) -> list[DownloadRecord]:
    relation, deleted = source_paths(raw_dir, snapshot, event)
    return [
        download(
            f"{RAW_ROOT}/model_relation/batch_all_{snapshot}.csv", relation
        ),
        download(
            f"{RAW_ROOT}/deleted_models/deleted_model_{event}.csv", deleted
        ),
    ]


def parse_base_models(value: str) -> tuple[str, ...]:
    if not value or value.strip().upper() == "N/A":
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def load_children(relation_path: Path) -> dict[str, set[str]]:
    """Return base-to-derived adjacency without retaining unrelated rows."""
    children: dict[str, set[str]] = {}
    with relation_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        expected = {"Model ID", "Type", "Base Model"}
        if set(reader.fieldnames or ()) != expected:
            raise ValueError(
                f"Unexpected relation schema in {relation_path}: {reader.fieldnames}"
            )
        for row in reader:
            child = row["Model ID"].strip()
            if not child:
                continue
            for base in parse_base_models(row["Base Model"]):
                children.setdefault(base, set()).add(child)
    return children


def load_deleted(deleted_path: Path) -> set[str]:
    with deleted_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if "Model ID" not in (reader.fieldnames or ()):
            raise ValueError(
                f"Missing Model ID column in {deleted_path}: {reader.fieldnames}"
            )
        return {
            row["Model ID"].strip()
            for row in reader
            if row.get("Model ID", "").strip()
        }


def write_manifest(records: Iterable[DownloadRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.__dict__ for record in records]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
