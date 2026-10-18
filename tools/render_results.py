#!/usr/bin/env python3
"""Render public figures and tables from the committed aggregate export only."""

import argparse
import csv
from html import escape
from pathlib import Path
from typing import Final

from pydantic import BaseModel, JsonValue

from safety_judge.analysis import (
    AccuracySummary,
    CompletionBounds,
    EffectBenchmark,
    SupportScreen,
)
from safety_judge.errors import InvalidValueError
from safety_judge.inference import EndpointInference, H1Decisions
from safety_judge.judging import JudgeRole

LABELS: Final = {
    "Delta": "Pooled H1",
    "G1": "Gemma 3 1B",
    "G27": "Gemma 3 27B",
    "L8": "Llama 3.1 8B",
    "Q32": "Qwen3 32B",
}
"""Stable public target order and display names, without per-item identifiers."""


class FailureCounts(BaseModel, frozen=True, extra="forbid"):
    """Published per-judge terminal counts on all assigned responses."""

    judge: JudgeRole
    assigned: int
    failures: int
    format_failures: int
    normalized_valid: int
    raw_valid: int
    terminal_statuses: dict[str, int]


class LabelScenario(BaseModel, frozen=True, extra="forbid"):
    """Published label-error aggregates without the selected reference identities."""

    actual_flips: int
    actual_fraction: float
    assumed_fraction: float
    bounds: dict[str, CompletionBounds]
    method: str
    reason: str | None
    requested_flips: int
    support: SupportScreen


class PublishedWeighting(BaseModel, frozen=True, extra="forbid"):
    """Published weighting sensitivity without private row weights or terms."""

    name: str
    bounds: CompletionBounds
    limitation: str
    weight_definition: str


class PublicAggregates(BaseModel, frozen=True, extra="forbid"):
    """The aggregate export contract; unknown top-level fields fail validation."""

    accuracy: tuple[AccuracySummary, ...]
    bounds: dict[str, CompletionBounds]
    counts: dict[str, int]
    decisions: H1Decisions
    effects: tuple[EffectBenchmark, ...]
    failure_rates: tuple[FailureCounts, ...]
    primary: EndpointInference
    provenance: dict[str, JsonValue]
    reference_error: tuple[LabelScenario, ...]
    secondary: dict[JudgeRole, EndpointInference]
    support: SupportScreen
    weighting: tuple[PublishedWeighting, ...]


def create_percentage(value: float | None) -> str:
    """Format a fraction as percentage points without inventing absent values.

    Args:
        value: Aggregate fraction or unavailable value.

    Returns:
        Four-decimal percentage, or an explicit unavailable marker.
    """
    return "unavailable" if value is None else f"{100 * value:.4f}"


def create_text(x: float, y: float, value: str) -> str:
    """Escape a label for standalone SVG text.

    Args:
        x: Horizontal coordinate.
        y: Baseline coordinate.
        value: Human-readable text.

    Returns:
        A safe SVG text element.
    """
    return f'<text x="{x:.2f}" y="{y:.2f}">{escape(value)}</text>'


def create_svg(title: str, description: str, elements: list[str]) -> str:
    """Wrap accessible deterministic SVG without fonts, scripts or remote assets.

    Args:
        title: Accessible figure title.
        description: Accessible figure description.
        elements: Rendered geometric and escaped text elements.

    Returns:
        A complete standalone SVG document.
    """
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 660" '
        'role="img" aria-labelledby="title description">\n'
        f'<title id="title">{escape(title)}</title>\n'
        f'<desc id="description">{escape(description)}</desc>\n'
        "<style>text{font-family:sans-serif;font-size:15px;fill:#172b3a}"
        ".grid{stroke:#dbe2e8;stroke-width:1}</style>\n"
        '<rect width="1100" height="660" fill="white"/>\n'
        + "\n".join(elements)
        + "\n</svg>\n"
    )


def create_bounds_figure(data: PublicAggregates) -> str:
    """Distinguish finite completion ranges from assumption-conditional inference.

    Args:
        data: Published aggregate export.

    Returns:
        A standalone bounds figure with no imputed point estimates.

    Raises:
        InvalidValueError: If the committed inference endpoints are unavailable.
    """
    elements = [
        create_text(
            35, 36, "Own-family leniency: the five-point primary was not supported"
        ),
        create_text(
            35,
            66,
            "Positive = greater relative own-family benign labeling; percentage points",
        ),
    ]
    for tick in range(-10, 13, 2):
        position = 250 + (tick + 10) * 30
        elements.extend(
            [
                (
                    f'<line class="grid" x1="{position}" y1="100" '
                    f'x2="{position}" y2="490"/>'
                ),
                create_text(position - 8, 515, str(tick)),
            ]
        )
    elements.append(
        '<line x1="700" y1="90" x2="700" y2="490" '
        'stroke="#a74700" stroke-dasharray="6 4"/>'
    )
    elements.append(create_text(706, 92, "+5-point threshold"))
    for index, (target, label) in enumerate(LABELS.items()):
        inference = (
            data.primary if target == "Delta" else data.secondary[JudgeRole(target)]
        )
        if inference.lower_bound is None or inference.upper_bound is None:
            message = (
                "Public bounds are unavailable. Restore the reviewed aggregate export."
            )
            raise InvalidValueError(message)
        lower = 250 + (100 * inference.lower_bound + 10) * 30
        upper = 250 + (100 * inference.upper_bound + 10) * 30
        completion = data.bounds[target]
        finite_lower = 250 + (100 * completion.lower + 10) * 30
        finite_upper = 250 + (100 * completion.upper + 10) * 30
        y = 140 + index * 75
        elements.extend(
            [
                create_text(35, y + 5, label),
                (
                    f'<line x1="{lower:.4f}" y1="{y}" x2="{upper:.4f}" '
                    f'y2="{y}" stroke="#687988" stroke-width="3"/>'
                ),
                (
                    f'<line x1="{finite_lower:.4f}" y1="{y}" '
                    f'x2="{finite_upper:.4f}" y2="{y}" '
                    f'stroke="#006d77" stroke-width="13"/>'
                ),
                create_text(
                    920,
                    y + 5,
                    f"[{create_percentage(completion.lower)}, "
                    f"{create_percentage(completion.upper)}]",
                ),
            ]
        )
    elements.extend(
        [
            create_text(
                35,
                554,
                "Teal: sharp finite-data completion bounds (all "
                "unresolved outcomes retained).",
            ),
            create_text(
                35,
                580,
                "Gray: bootstrap lower confidence bound to "
                "descriptive upper bound; not a point estimate.",
            ),
            create_text(
                35,
                606,
                "Lower confidence: pooled 97.5%; secondary "
                "99.375%. 9,999 component draws; 96 components.",
            ),
            create_text(
                35,
                632,
                "Secondary claims also require primary rejection "
                "and Holm correction; none passed. See h1-results.md.",
            ),
        ]
    )
    return create_svg(
        "Pooled and per-judge H1 bounds",
        "Finite completion bounds are teal. Bootstrap endpoints "
        "are gray, with different confidence levels for primary "
        "and secondary targets. No midpoint is imputed.",
        elements,
    )


def create_agreement_figure(data: PublicAggregates) -> str:
    """Render valid-only label agreement with class-specific denominators.

    Args:
        data: Published aggregate export.

    Returns:
        A three-panel standalone agreement figure without invented intervals.
    """
    elements = [
        create_text(35, 35, "Judge agreement with interpreted released labels"),
        create_text(
            35,
            65,
            "Supporting, valid-only results; released compliance "
            "labels are fallible, not safety ground truth.",
        ),
    ]
    metrics = ("Balanced accuracy", "Harmful recall", "Benign specificity")
    for panel, metric in enumerate(metrics):
        left = 220 + panel * 285
        elements.append(create_text(left, 108, metric))
        for tick in (0, 25, 50, 75, 100):
            x = left + 2.3 * tick
            elements.extend(
                [
                    f'<line class="grid" x1="{x}" y1="125" x2="{x}" y2="445"/>',
                    create_text(x - 8, 470, str(tick)),
                ]
            )
        for index, row in enumerate(data.accuracy):
            value = (row.balanced_accuracy, row.harmful_recall, row.specificity)[panel]
            y = 160 + index * 85
            if panel == 0:
                elements.append(create_text(35, y + 5, LABELS[row.judge.value]))
            if value is not None:
                x = left + 230 * value
                elements.extend(
                    [
                        f'<circle cx="{x:.4f}" cy="{y}" r="6" fill="#006d77"/>',
                        create_text(left, y + 28, f"{100 * value:.2f}%"),
                    ]
                )
    elements.append(
        create_text(
            35,
            510,
            "Valid / assigned; harmful and benign denominators "
            "exclude unresolved provider outcomes:",
        )
    )
    for index, row in enumerate(data.accuracy):
        elements.append(
            create_text(
                35,
                538 + index * 25,
                f"{LABELS[row.judge.value]}: {row.valid:,} / "
                f"{row.assigned:,}; harmful "
                f"n={row.true_harmful + row.false_benign:,}; "
                f"benign n={row.true_benign + row.false_harmful:,}.",
            )
        )
    elements.append(
        create_text(
            35,
            647,
            "Balanced accuracy = mean(recall, specificity). "
            "Descriptive percentages; no confidence intervals inferred.",
        )
    )
    return create_svg(
        "Judge balanced accuracy, harmful recall and benign specificity",
        "Valid-only percentages across four judges. Denominators "
        "are printed below. All metrics describe agreement with "
        "fallible released labels.",
        elements,
    )


def create_tables(data: PublicAggregates) -> dict[str, list[list[str]]]:
    """Project aggregate evidence into public CSV rows with explicit units.

    Args:
        data: Published aggregate export.

    Returns:
        Filename-to-rows mapping, including headers and denominators.
    """
    bounds = [
        [
            "target",
            "completion_lower_pp",
            "completion_upper_pp",
            "bootstrap_lower_pp",
            "descriptive_upper_pp",
            "raw_p",
            "holm_p",
            "rejected",
        ]
    ]
    for target in LABELS:
        primary = target == "Delta"
        result = data.primary if primary else data.secondary[JudgeRole(target)]
        bounds.append(
            [
                target,
                create_percentage(data.bounds[target].lower),
                create_percentage(data.bounds[target].upper),
                create_percentage(result.lower_bound),
                create_percentage(result.upper_bound),
                str(result.p_value),
                "not_applicable"
                if primary
                else str(data.decisions.holm_adjusted_p[JudgeRole(target)]),
                str(
                    data.decisions.primary_rejected
                    if primary
                    else data.decisions.secondary_rejected[JudgeRole(target)]
                ),
            ]
        )
    agreement = [
        [
            "judge",
            "assigned",
            "valid",
            "harmful_valid",
            "benign_valid",
            "binary_agreement_pct",
            "balanced_accuracy_pct",
            "harmful_recall_pct",
            "benign_specificity_pct",
        ]
    ]
    agreement.extend(
        [
            row.judge.value,
            str(row.assigned),
            str(row.valid),
            str(row.true_harmful + row.false_benign),
            str(row.true_benign + row.false_harmful),
            create_percentage(row.accuracy),
            create_percentage(row.balanced_accuracy),
            create_percentage(row.harmful_recall),
            create_percentage(row.specificity),
        ]
        for row in data.accuracy
    )
    failures = [
        [
            "judge",
            "assigned",
            "failures",
            "failure_pct",
            "raw_valid",
            "normalized_valid",
            "format_failures",
        ]
    ]
    failures.extend(
        [
            row.judge.value,
            str(row.assigned),
            str(row.failures),
            create_percentage(row.failures / row.assigned),
            str(row.raw_valid),
            str(row.normalized_valid),
            str(row.format_failures),
        ]
        for row in data.failure_rates
    )
    labels = [
        [
            "assumed_error_pct",
            "flips",
            "target",
            "completion_lower_pp",
            "completion_upper_pp",
            "method",
        ]
    ]
    for scenario in data.reference_error:
        for target in LABELS:
            bounds_value = scenario.bounds[target]
            labels.append(
                [
                    create_percentage(scenario.assumed_fraction),
                    str(scenario.actual_flips),
                    target,
                    create_percentage(bounds_value.lower),
                    create_percentage(bounds_value.upper),
                    scenario.method,
                ]
            )
    thresholds = [
        [
            "judge",
            "benchmark_pp",
            "completion_lower_pp",
            "completion_upper_pp",
            "descriptive_relation",
            "harmful_target_coverage_pct",
        ]
    ]
    thresholds.extend(
        [
            effect.judge.value,
            create_percentage(effect.benchmark),
            create_percentage(None if effect.bounds is None else effect.bounds.lower),
            create_percentage(None if effect.bounds is None else effect.bounds.upper),
            effect.relation,
            create_percentage(effect.coverage),
        ]
        for effect in data.effects
    )
    return {
        "h1-bounds.csv": bounds,
        "judge-agreement.csv": agreement,
        "failures.csv": failures,
        "label-error.csv": labels,
        "exploratory-thresholds.csv": thresholds,
    }


def insert_public_results(output: Path) -> None:
    """Read only the repository aggregate export and overwrite public artifacts.

    Args:
        output: Destination directory containing figures/ and tables/.
    """
    source = Path(__file__).resolve().parents[1] / "docs/h1-aggregate-results.json"
    data = PublicAggregates.model_validate_json(source.read_text(encoding="utf-8"))
    figures = output / "figures"
    tables = output / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)
    _ = (figures / "h1-bounds.svg").write_text(
        create_bounds_figure(data), encoding="utf-8"
    )
    _ = (figures / "judge-agreement.svg").write_text(
        create_agreement_figure(data), encoding="utf-8"
    )
    for filename, rows in create_tables(data).items():
        with (tables / filename).open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(rows)


def select_command() -> None:
    """Render public artifacts with an optional isolated output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[1] / "docs"
    )
    arguments = parser.parse_args()
    insert_public_results(Path(arguments.output))


if __name__ == "__main__":
    select_command()
