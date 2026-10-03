import csv

import pytest

from mirrorplan.data import load_children, load_deleted, parse_base_models


def test_parse_base_models_preserves_all_declared_inputs() -> None:
    assert parse_base_models("") == ()
    assert parse_base_models(" N/A ") == ()
    assert parse_base_models("owner/a, owner/b ,owner/c") == (
        "owner/a",
        "owner/b",
        "owner/c",
    )


def test_csv_importers_handle_bom_merges_and_blank_ids(tmp_path) -> None:
    relation_path = tmp_path / "relation.csv"
    with relation_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Model ID", "Type", "Base Model"])
        writer.writeheader()
        writer.writerows(
            [
                {"Model ID": "derived/x", "Type": "merge", "Base Model": "base/a, base/b"},
                {"Model ID": "derived/y", "Type": "adapter", "Base Model": "base/a"},
                {"Model ID": "", "Type": "model", "Base Model": "base/c"},
            ]
        )
    deletion_path = tmp_path / "deleted.csv"
    with deletion_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Model ID", "Reason"])
        writer.writeheader()
        writer.writerows(
            [
                {"Model ID": " base/a ", "Reason": "missing"},
                {"Model ID": "", "Reason": "blank"},
            ]
        )

    assert load_children(relation_path) == {
        "base/a": {"derived/x", "derived/y"},
        "base/b": {"derived/x"},
    }
    assert load_deleted(deletion_path) == {"base/a"}


def test_relation_importer_rejects_schema_drift(tmp_path) -> None:
    path = tmp_path / "relation.csv"
    path.write_text("Model ID,Base Model\na,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected relation schema"):
        load_children(path)
