"""Public artifact rendering is deterministic and limited to aggregate evidence."""

import csv
import runpy
import sys
from pathlib import Path

lazy import pytest


def test_public_artifacts_reproduce_committed_tables_and_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "tools/render_results.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--output", str(tmp_path)])
    _ = runpy.run_path(str(script), run_name="__main__")
    expected = {
        "figures/h1-bounds.svg",
        "figures/judge-agreement.svg",
        "tables/h1-bounds.csv",
        "tables/judge-agreement.csv",
        "tables/failures.csv",
        "tables/label-error.csv",
        "tables/exploratory-thresholds.csv",
    }
    actual = {
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert actual == expected
    for relative in sorted(expected):
        assert (tmp_path / relative).read_bytes() == (
            root / "docs" / relative
        ).read_bytes(), relative
    with (tmp_path / "tables/h1-bounds.csv").open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["completion_lower_pp"] == "0.4333"
    assert rows[0]["completion_upper_pp"] == "0.5971"
    assert rows[0]["bootstrap_lower_pp"] == "-2.5837"
    assert rows[0]["rejected"] == "False"
    with (tmp_path / "tables/judge-agreement.csv").open(encoding="utf-8") as stream:
        agreement = list(csv.DictReader(stream))
    assert agreement[0]["harmful_valid"] == "5170"
    assert agreement[0]["benign_valid"] == "1379"
    assert agreement[0]["benign_specificity_pct"] == "16.8238"


def test_public_renderer_reads_only_the_aggregate_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "tools/render_results.py"
    original_read = Path.read_text
    reads: list[Path] = []

    def select_recorded_text(path: Path, encoding: str = "utf-8") -> str:
        """Record the renderer's explicit text-file boundary.

        Args:
            path: Requested text file.
            encoding: Text encoding.

        Returns:
            File contents read through the original boundary.
        """
        reads.append(path.resolve())
        return original_read(path, encoding=encoding)

    monkeypatch.setattr(Path, "read_text", select_recorded_text)
    monkeypatch.setattr(sys, "argv", [str(script), "--output", str(tmp_path)])
    _ = runpy.run_path(str(script), run_name="__main__")
    assert reads == [root / "docs/h1-aggregate-results.json"]
    for path in tmp_path.rglob("*.svg"):
        rendered = original_read(path, encoding="utf-8")
        assert '<title id="title">' in rendered
        assert '<desc id="description">' in rendered
        assert "<script" not in rendered
        assert "href=" not in rendered
        assert "runs/" not in rendered
