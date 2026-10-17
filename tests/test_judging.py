"""Blinded visible text and strict terminal outcomes preserve failure coverage."""

import json
from typing import Literal

import pytest
from pydantic import ValidationError

from safety_judge.judging import (
    FrozenRubric,
    OrdinalJudgment,
    UnresolvedJudgment,
    create_judge_request,
    create_normalized_judge_text,
    create_normalized_terminal_outcomes,
    create_strict_terminal_outcome,
    create_terminal_outcome,
)


def test_request_keeps_source_refusal_as_text_and_exposes_only_visible_fields() -> None:
    rubric = FrozenRubric(
        version="synthetic-v1", text="Synthetic rubric.", source="synthetic"
    )
    request = create_judge_request(" question\n", "I cannot answer.\n ", rubric)
    visible = json.loads(request.messages[1].content)
    assert visible == {"request": " question\n", "response": "I cannot answer.\n "}
    assert request == create_judge_request(" question\n", "I cannot answer.\n ", rubric)
    assert set(visible) == {"request", "response"}
    assert len(request.visible_text_sha256) == 64


@pytest.mark.parametrize("ordinal", [1, 2, 3, 4, 5])
def test_each_integer_ordinal_is_accepted(ordinal: int) -> None:
    outcome = create_strict_terminal_outcome(
        json.dumps({"ordinal": ordinal}), finish="complete", judge_refused=False
    )
    assert isinstance(outcome, OrdinalJudgment)
    assert outcome.ordinal == ordinal


@pytest.mark.parametrize(
    "raw",
    [
        '{"ordinal":true}',
        '{"ordinal":"3"}',
        '{"ordinal":3.0}',
        '{"ordinal":0}',
        '{"ordinal":6}',
        '{"ordinal":3,"extra":1}',
        '{"ordinal":1,"ordinal":3}',
        "3",
        "[]",
        "null",
        'answer: {"ordinal":3}',
        '```json\n{"ordinal":3}\n```',
        "",
    ],
)
def test_invalid_outputs_remain_unresolved(raw: str) -> None:
    assert create_strict_terminal_outcome(
        raw, finish="complete", judge_refused=False
    ) == UnresolvedJudgment(reason="parse_error")


def test_judge_refusal_takes_precedence_over_a_parseable_ordinal() -> None:
    assert create_strict_terminal_outcome(
        '{"ordinal":1}', finish="complete", judge_refused=True
    ) == UnresolvedJudgment(reason="judge_refusal")


@pytest.mark.parametrize("finish", ["truncated", "unknown"])
def test_incomplete_provider_finish_cannot_become_a_valid_judgment(
    finish: Literal["truncated", "unknown"],
) -> None:
    outcome = create_strict_terminal_outcome(
        '{"ordinal":1}', finish=finish, judge_refused=False
    )
    assert isinstance(outcome, UnresolvedJudgment)
    assert outcome.reason == finish


@pytest.mark.parametrize("ordinal", [True, False, 1.0, 5.0, "1", 0, 6])
def test_domain_judgments_reject_noninteger_or_out_of_domain_ordinals(
    ordinal: object,
) -> None:
    with pytest.raises(ValidationError):
        _ = OrdinalJudgment.model_validate({"ordinal": ordinal})
    with pytest.raises(ValidationError):
        _ = OrdinalJudgment.model_validate_json(json.dumps({"ordinal": ordinal}))


@pytest.mark.parametrize("ordinal", [1, 2, 3, 4, 5])
def test_domain_judgments_preserve_every_strict_integer_ordinal(ordinal: int) -> None:
    judgment = OrdinalJudgment.model_validate({"ordinal": ordinal})
    assert judgment.ordinal == ordinal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('  {"ordinal":3}\n', '{"ordinal":3}'),
        ('```\n{"ordinal":3}\n```', '{"ordinal":3}\n'),
        (' \n```json\n {"ordinal":3} \n```\t', ' {"ordinal":3} \n'),
        ('```JSON-1_+\r\n{"ordinal":3}\r\n```', '{"ordinal":3}\r\n'),
        ('```json\n{"ordinal":3}', '```json\n{"ordinal":3}'),
        ('```{"ordinal":3}```', '```{"ordinal":3}```'),
        ('````json\n{"ordinal":3}\n````', '{"ordinal":3}\n'),
        ('```\n```json\n{"ordinal":3}\n```\n```', '```json\n{"ordinal":3}\n```\n'),
    ],
)
def test_fixed_normalizer_removes_only_one_outer_fence_and_preserves_interior(
    text: str, expected: str
) -> None:
    assert create_normalized_judge_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"ordinal":3}\n```',
        '```\n{"ordinal":3}\n```',
        '~~~ json\r\n{"ordinal":3}\r\n~~~~',
        '````json\n{"ordinal":3}\n`````',
        '``` json \t\n{"ordinal":3}\n``` \t',
        '\n ```json\n{"ordinal":3}\n``` \n',
    ],
)
def test_normalized_strict_success_keeps_parallel_raw_format_failure(text: str) -> None:
    outcomes = create_normalized_terminal_outcomes(
        text, finish="complete", judge_refused=False
    )
    assert outcomes.version == "outer-markdown-fence-v1"
    assert outcomes.raw == UnresolvedJudgment(reason="parse_error")
    assert outcomes.normalized == OrdinalJudgment(ordinal=3)


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"ordinal":3}',
        '```json\n{"ordinal":3}\n```\nprose',
        'prose\n```json\n{"ordinal":3}\n```',
        '```\n```json\n{"ordinal":3}\n```\n```',
        '```json\n{"ordinal":3}\n```\n```json\n{"ordinal":3}\n```',
        '```json\n{"ordinal":3,}\n```',
        '```json\n{"ordinal":"3"}\n```',
        '```json\n{"ordinal":true}\n```',
        '```json\n{"ordinal":1,"ordinal":3}\n```',
        "```json\n3\n```",
        '```json\n{"ordinal":3,"extra":1}\n```',
        '``` json two\n{"ordinal":3}\n```',
        '````json\n{"ordinal":3}\n```',
        '~~~json\n{"ordinal":3}\n```',
    ],
)
def test_normalization_never_repairs_invalid_inner_or_multiple_or_prose_outputs(
    text: str,
) -> None:
    outcomes = create_normalized_terminal_outcomes(
        text, finish="complete", judge_refused=False
    )
    assert outcomes.raw == UnresolvedJudgment(reason="parse_error")
    assert outcomes.normalized == UnresolvedJudgment(reason="parse_error")


@pytest.mark.parametrize(
    ("finish", "refused", "reason"),
    [
        ("truncated", False, "truncated"),
        ("unknown", False, "unknown"),
        ("complete", True, "judge_refusal"),
    ],
)
def test_normalization_preserves_provider_refusal_and_finish_precedence(
    finish: Literal["complete", "truncated", "unknown"], *, refused: bool, reason: str
) -> None:
    outcomes = create_normalized_terminal_outcomes(
        '```json\n{"ordinal":3}\n```', finish=finish, judge_refused=refused
    )
    assert outcomes.normalized.kind == "unresolved"
    assert outcomes.normalized.reason == reason


def test_shared_judge_boundary_normalizes_before_the_unchanged_strict_decoder() -> None:
    text = '```json\n{"ordinal":3}\n```'
    assert create_terminal_outcome(
        text, finish="complete", judge_refused=False
    ) == OrdinalJudgment(ordinal=3)
    assert create_strict_terminal_outcome(
        text, finish="complete", judge_refused=False
    ) == UnresolvedJudgment(reason="parse_error")
