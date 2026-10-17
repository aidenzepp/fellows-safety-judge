"""Source bytes, labels, conflict exclusion, and explicit lineage stay auditable."""

import csv
import hashlib
import io
import json
lazy from pathlib import Path

import pytest
from pydantic import ValidationError

from safety_judge.coin_flip import (
    AcceptedSourceDecision,
    create_behavior_crosswalk,
    create_eligible_responses,
    create_reference_ordinal,
    create_source_audit,
    create_source_inventory,
    create_source_manifest,
    create_source_manifest_sha256,
    select_source_inventory,
)
from safety_judge.errors import InvalidValueError


def create_source_bytes(records: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "Prompt",
            "Generation",
            "Model",
            "Attack",
            "Human_Judgement",
            "Behavior_ID",
            "Attack_Iteration",
        ]
    )
    writer.writerows(records)
    return b"\xef\xbb\xbf" + stream.getvalue().encode()


def test_csv_preserves_multiline_quotes_whitespace_blanks_and_raw_bytes() -> None:
    original = create_source_bytes(
        [
            [
                '  question,"quoted"\r\nnext',
                " response\nnext ",
                "Gemma-1B",
                "Direct",
                ".5",
                "goal",
                "",
            ],
            [
                '  question,"quoted"\r\nnext',
                "other",
                "Gemma-1B",
                "Direct",
                ".25",
                "",
                "",
            ],
        ]
    )
    inventory = create_source_inventory(original)
    assert inventory.raw_bytes == original
    assert inventory.sha256 == hashlib.sha256(original).hexdigest()
    assert inventory.rows[0].number == 0
    assert inventory.rows[0].fields[0] == '  question,"quoted"\r\nnext'
    assert inventory.rows[0].fields[1] == " response\nnext "
    assert inventory.rows[1].fields[5] == ""
    audit = create_source_audit(inventory, component_links=())
    assert audit.responses[0].harmful
    assert not audit.responses[1].harmful
    assert audit.responses[1].behavior_identifier == "goal"
    assert audit.responses[1].behavior_was_derived
    assert audit.visible_utf8_bytes_sum == sum(
        len(response.prompt.encode()) + len(response.generation.encode())
        for response in audit.responses
    )


@pytest.mark.parametrize(
    ("raw", "ordinal"), [("0", 1), (".25", 2), (".5", 3), (".75", 4), ("1", 5)]
)
def test_affine_label_mapping_retains_every_released_grid_point(
    raw: str, ordinal: int
) -> None:
    assert create_reference_ordinal(raw) == ordinal


@pytest.mark.parametrize("raw", [".1", "-1", "1.25", "NaN", "Infinity", "", "true"])
def test_off_grid_or_nonnumeric_labels_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidValueError):
        _ = create_reference_ordinal(raw)


def test_conflicts_exclude_every_copy_and_duplicates_keep_the_first_ordinal() -> None:
    records = [
        ["question", "same", "Llama-3.1", "BoN", ".25", "goal", ""],
        ["question", "same", "Llama-3.1", "BoN", "0", "goal", ""],
        ["question", "agree", "Llama-3.1", "BoN", ".75", "goal", ""],
        ["question", "agree", "Llama-3.1", "BoN", ".75", "", ""],
        ["question", "agree", "Llama-3.1", "BoN", ".75", "", "2"],
    ]
    audit = create_source_audit(
        create_source_inventory(create_source_bytes(records)), component_links=()
    )
    assert audit.conflict_ordinals == (0, 1)
    assert audit.duplicate_ordinals == (3,)
    assert [response.row_number for response in audit.responses] == [2, 4]
    assert (
        audit.responses[0].component_identifier
        == audit.responses[1].component_identifier
    )


@pytest.mark.parametrize("behavior", ["different", ""])
def test_ambiguous_or_unevidenced_prompt_crosswalks_are_rejected(behavior: str) -> None:
    records = [["question", "response", "Gemma-1B", "Direct", "0", behavior, ""]]
    if behavior:
        records.append(["question", "other", "Gemma-1B", "Direct", "0", "first", ""])
    inventory = create_source_inventory(create_source_bytes(records))
    with pytest.raises(InvalidValueError):
        _ = create_behavior_crosswalk(inventory)


def test_components_union_only_accepted_edges_and_choose_lexical_minimum() -> None:
    records = [
        [name, "response", "Gemma-1B", "Direct", "0", name, ""]
        for name in ("z", "a", "b")
    ]
    audit = create_source_audit(
        create_source_inventory(create_source_bytes(records)),
        component_links=(("z", "b"), ("b", "a")),
    )
    assert audit.behavior_component_pairs == (("a", "a"), ("b", "a"), ("z", "a"))


def test_manifest_cannot_silently_omit_rows_or_include_and_exclude_one_row() -> None:
    inventory = create_source_inventory(
        create_source_bytes(
            [["question", "response", "Gemma-1B", "Direct", "0", "goal", ""]]
        )
    )
    with pytest.raises(InvalidValueError):
        _ = create_eligible_responses(inventory, ())
    with pytest.raises(InvalidValueError):
        _ = create_eligible_responses(
            inventory,
            (
                AcceptedSourceDecision(
                    row_number=0,
                    component_identifier="goal",
                    exclusion_reason="excluded",
                ),
            ),
        )


def test_source_inventory_cannot_be_mutated() -> None:
    inventory = create_source_inventory(create_source_bytes([]))
    with pytest.raises(ValidationError):
        inventory.sha256 = "changed"  # pyright: ignore[reportAttributeAccessIssue] -- exercise the runtime immutability guard


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"Prompt,Prompt\n",
        b"Prompt,Generation,Model,Attack,Human_Judgement,Behavior_ID\nshort\n",
    ],
)
def test_malformed_csv_is_rejected_without_partial_inventory(raw: bytes) -> None:
    with pytest.raises(InvalidValueError):
        _ = create_source_inventory(raw)


def test_manifest_hash_matches_canonical_ascii_json_without_a_trailing_newline() -> (
    None
):
    inventory = create_source_inventory(
        create_source_bytes(
            [
                ["question", "response", "Gemma-1B", "Direct", "0", "goal", ""],
            ]
        )
    )
    audit = create_source_audit(inventory, component_links=())
    manifest = create_source_manifest(inventory, audit, (0,))
    expected = {
        "source_sha256": inventory.sha256,
        "eligible_ordinals": [0],
        "behavior_component_pairs": [["goal", "goal"]],
        "pilot_ordinals": [0],
    }
    assert (
        create_source_manifest_sha256(manifest)
        == hashlib.sha256(
            json.dumps(
                expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
    )
    for invalid_sample in ((0, 0), (1,)):
        with pytest.raises(InvalidValueError):
            _ = create_source_manifest(inventory, audit, invalid_sample)


def test_local_read_retains_bytes_and_reports_missing_files(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    raw = create_source_bytes([])
    _ = path.write_bytes(raw)
    assert select_source_inventory(path).raw_bytes == raw
    with pytest.raises(InvalidValueError) as raised:
        _ = select_source_inventory(tmp_path / "absent.csv")
    assert isinstance(raised.value.__cause__, OSError)


def test_unknown_component_edges_cannot_create_unobserved_behaviors() -> None:
    inventory = create_source_inventory(
        create_source_bytes(
            [
                ["question", "response", "Gemma-1B", "Direct", "0", "goal", ""],
            ]
        )
    )
    with pytest.raises(InvalidValueError):
        _ = create_source_audit(inventory, component_links=(("goal", "absent"),))


def test_source_refusal_is_eligible_and_does_not_become_a_judge_refusal() -> None:
    inventory = create_source_inventory(
        create_source_bytes(
            [
                ["question", "I cannot answer.", "Gemma-1B", "Direct", "0", "goal", ""],
            ]
        )
    )
    audit = create_source_audit(inventory, component_links=())
    assert audit.responses[0].generation == "I cannot answer."
    assert audit.responses[0].reference == 1
    assert not audit.responses[0].harmful
