"""The complete offline CLI composes source, mock journal, replay and fixed reports."""

import csv
import json
lazy from pathlib import Path

import pytest

from safety_judge.__main__ import select_command_line
from safety_judge.reporting import StudyReport
from safety_judge.study import StudyConfiguration


def insert_fixture_source(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(
            (
                "Prompt",
                "Generation",
                "Model",
                "Attack",
                "Human_Judgement",
                "Behavior_ID",
                "Attack_Iteration",
            )
        )
        for index, model in enumerate(
            ("Gemma-1B", "Gemma-27B", "Llama-3.1", "Qwen-3-32B")
        ):
            writer.writerow(
                (
                    f"Harmless question {index}",
                    "Harmless response",
                    model,
                    "Direct",
                    ".5",
                    f"behavior-{index}",
                    "",
                )
            )


def test_offline_audit_prepare_mock_replay_report_never_requires_credentials(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.csv"
    insert_fixture_source(source)
    audit = tmp_path / "source.json"
    links = tmp_path / "links.json"
    _ = links.write_text("[]")
    assert (
        select_command_line(
            [
                "audit",
                "--source",
                str(source),
                "--output",
                str(audit),
                "--component-links",
                str(links),
            ]
        )
        == 0
    )
    rubric = tmp_path / "rubric.json"
    _ = rubric.write_text(
        json.dumps(
            {
                "version": "fixture-v1",
                "text": "Synthetic ordinal rubric.",
                "source": "synthetic-fixture",
            }
        )
    )
    parameters = tmp_path / "parameters.json"
    _ = parameters.write_text(
        json.dumps(
            {"maximum_output_tokens": 32, "temperature": 0, "timeout_seconds": 1}
        )
    )
    configuration = tmp_path / "configuration.json"
    assert (
        select_command_line(
            [
                "prepare",
                "--source",
                str(audit),
                "--rubric",
                str(rubric),
                "--parameters",
                str(parameters),
                "--run",
                "fixture",
                "--output",
                str(configuration),
            ]
        )
        == 0
    )
    prepared = StudyConfiguration.model_validate_json(configuration.read_bytes())
    assert not prepared.budget.confirmed
    assert not any(prepared.gates.model_dump().values())
    synthetic = tmp_path / "synthetic.json"
    journal = tmp_path / "journal.jsonl"
    outcomes = tmp_path / "outcomes.json"
    assert (
        select_command_line(
            [
                "mock-dry-run",
                "--configuration",
                str(configuration),
                "--frozen-output",
                str(synthetic),
                "--journal",
                str(journal),
                "--output",
                str(outcomes),
            ]
        )
        == 0
    )
    assert len(json.loads(outcomes.read_text())["judgments"]) == 16
    replay = tmp_path / "replay.json"
    assert (
        select_command_line(
            [
                "inspect",
                "--configuration",
                str(synthetic),
                "--journal",
                str(journal),
                "--output",
                str(replay),
            ]
        )
        == 0
    )
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    assert (
        select_command_line(
            [
                "report",
                "--configuration",
                str(synthetic),
                "--journal",
                str(journal),
                "--output",
                str(output),
                "--markdown",
                str(markdown),
                "--replicates",
                "9",
            ]
        )
        == 0
    )
    report = StudyReport.model_validate_json(output.read_bytes())
    assert report.evidence_kind == "synthetic"
    assert len(report.effects) == 12
    assert len(report.reference_error) == 3
    assert set(report.secondary) == set(prepared.prices)
    assert report.primary is not None
    assert report.primary.reason is not None
    assert "synthetic" in markdown.read_text()
    requests = tmp_path / "requests.json"
    assert (
        select_command_line(
            [
                "review-requests",
                "--configuration",
                str(configuration),
                "--output",
                str(requests),
            ]
        )
        == 0
    )
    assert json.loads(requests.read_text())["execution_allowed"] is False
    assert report.configuration_sha256 is not None
    contract = tmp_path / "contract.json"
    _ = contract.write_text(
        json.dumps(
            {
                "pilot_case_identifiers": [],
                "original_configuration_sha256": report.configuration_sha256,
                "rubric": prepared.rubric.model_dump(mode="json"),
                "paraphraser": {
                    "model": "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
                    "family": "mistral",
                },
                "reviewer": {
                    "model": "anthropic/claude-sonnet-4-6",
                    "family": "anthropic",
                },
                "presentation_version": "synthetic-v1",
                "independently_saved": True,
                "source_labels_hidden": True,
                "other_review_hidden": True,
                "judge_outputs_hidden": True,
            }
        )
    )
    cases = tmp_path / "cases.json"
    records = tmp_path / "records.json"
    _ = cases.write_text("[]")
    _ = records.write_text("[]")
    gate = tmp_path / "gate.json"
    assert (
        select_command_line(
            [
                "review-import",
                "--contract",
                str(contract),
                "--cases",
                str(cases),
                "--records",
                str(records),
                "--main-report",
                str(output),
                "--output",
                str(gate),
            ]
        )
        == 0
    )
    assert json.loads(gate.read_text())["rewritten_judging_allowed"] is False
    assert (
        "fixed_forty_distinct_cases"
        in json.loads(gate.read_text())["contract_failures"]
    )


def test_help_lists_offline_operations_without_a_live_execution_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as result:
        _ = select_command_line(["--help"])
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "mock-dry-run" in output
    assert "estimate" in output
    assert "review-import" in output


def test_missing_source_returns_an_actionable_nonzero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        select_command_line(
            [
                "audit",
                "--source",
                str(tmp_path / "missing.csv"),
                "--output",
                str(tmp_path / "output.json"),
            ]
        )
        == 2
    )
    assert "Offline command failed" in capsys.readouterr().err
