"""Freeze explicit offline study inputs without granting execution authority."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from safety_judge.analysis import SupportScreen, create_pre_call_support_screen
from safety_judge.artifacts import RunManifest, create_artifact_digest
from safety_judge.budget import ArmCap, BudgetPlan, FundingCommitment, TokenPrice
from safety_judge.coin_flip import EligibleResponse, SourceAudit, SourceManifest
from safety_judge.errors import InvalidValueError
from safety_judge.judging import FrozenRubric, JudgeRole, create_judge_request
from safety_judge.model_access import (
    GenerationParameters,
    ModelRoute,
    create_model_route,
)
from safety_judge.review import PilotSelection


class OfflineSource(BaseModel, frozen=True, extra="forbid"):
    """Audited local source with the fixed pilot or explicit infeasible sample.

    Attributes:
        source: Exact source/eligibility/component and pilot freeze.
        audit: Original decisions, exclusions, byte counts and accepted records.
        pilot: Frozen quota sample or explicit no-go disposition.
        support: Outcome-independent pre-call component and leverage screen.
    """

    source: SourceManifest
    audit: SourceAudit
    pilot: PilotSelection
    support: SupportScreen


class ExecutionGates(BaseModel, frozen=True, extra="forbid"):
    """Independent evidence gates; spending approval alone cannot enable calls.

    Attributes:
        execution_confirmed: Explicit authority to execute this frozen study.
        source_confirmed: Accepted eligibility, linkage and support decision.
        tokens_confirmed: Complete per-request token bounds have been established.
        rates_confirmed: Complete current account-specific billing is established.
        funding_confirmed: Gross commitments and all account liabilities are known.
        runtime_confirmed: Routes and generation controls are independently cleared.
    """

    execution_confirmed: bool = False
    source_confirmed: bool = False
    tokens_confirmed: bool = False
    rates_confirmed: bool = False
    funding_confirmed: bool = False
    runtime_confirmed: bool = False


class RunAssignment(BaseModel, frozen=True, extra="forbid"):
    """One fixed original/judge cell with a complete conservative input bound.

    Attributes:
        identifier: Stable response/role identity shared by retry attempts.
        response_identifier: Accepted source response identity.
        judge: Nominal judge; no substitutions or sampling.
        maximum_input_tokens: Complete billing bound, absent until measured.
    """

    identifier: str
    response_identifier: str
    judge: JudgeRole
    maximum_input_tokens: Annotated[int, Field(ge=0, strict=True)] | None


class StudyConfiguration(BaseModel, frozen=True, extra="forbid"):
    """A secret-free immutable source, presentation, route and budget snapshot.

    Attributes:
        run: Explicit durable run identity.
        evidence_kind: Synthetic fixture or real study provenance, never inferred.
        execution_mode: Simulation is distinct from authorized live execution.
        source: Accepted source/linkage/pilot freeze.
        support: Exact outcome-independent screen of these frozen source records.
        responses: Every eligible original, retaining labels outside model requests.
        rubric: Versioned exact proposed or approved compliance presentation.
        parameters: Explicit generation bounds, not budget-derived truncation.
        routes: Exactly the four fixed nominal judge routes.
        prices: Per-role complete billing metadata, potentially unconfirmed.
        budget: Explicit monetary authority; drafts remain unfunded.
        gates: Independent live execution prerequisites, all closed by default.
        assignments: Complete four-judge matrix in deterministic row order.
        maximum_workers: Bound on outstanding one-attempt network operations.
        maximum_per_provider: Bound on concurrent attempts on each account.
    """

    run: Annotated[str, Field(min_length=1)]
    evidence_kind: Literal["synthetic", "study"] = "study"
    execution_mode: Literal["simulated", "live"] = "live"
    source: SourceManifest
    support: SupportScreen
    responses: tuple[EligibleResponse, ...]
    rubric: FrozenRubric
    parameters: GenerationParameters
    routes: tuple[ModelRoute, ...]
    prices: dict[JudgeRole, TokenPrice]
    budget: BudgetPlan
    gates: ExecutionGates = ExecutionGates()
    assignments: tuple[RunAssignment, ...]
    maximum_workers: Annotated[int, Field(ge=1, le=128, strict=True)] = 2
    maximum_per_provider: Annotated[int, Field(ge=1, le=128, strict=True)] = 1

    @model_validator(mode="after")
    def create_validated_matrix(self) -> StudyConfiguration:
        """Reject missing, duplicate, changed-route or out-of-order assignments.

        Returns:
            This frozen complete original matrix.

        Raises:
            InvalidValueError: If source identities or fixed assignments differ.
        """
        expected = tuple(
            (row.identifier, role) for row in self.responses for role in JudgeRole
        )
        actual = tuple(
            (item.response_identifier, item.judge) for item in self.assignments
        )
        if (
            not self.responses
            or actual != expected
            or self.support != create_pre_call_support_screen(self.responses)
            or len({item.identifier for item in self.assignments}) != len(actual)
            or tuple(row.row_number for row in self.responses)
            != self.source.eligible_ordinals
            or any(
                row.identifier != f"{self.source.source_sha256}:{row.row_number}"
                for row in self.responses
            )
            or self.routes != tuple(create_model_route(role) for role in JudgeRole)
            or set(self.prices) != set(JudgeRole)
            or any(
                self.prices[role].account != create_model_route(role).provider
                for role in self.prices
            )
        ):
            message = (
                "Frozen source or all-four matrix differs; prepare the complete study."
            )
            raise InvalidValueError(message)
        return self


def create_configuration_digest(configuration: StudyConfiguration) -> str:
    """Hash the complete secret-free frozen configuration with canonical JSON.

    Args:
        configuration: Complete source, requests, routes, money and authority.

    Returns:
        Stable content digest used to reject changed resumes.
    """
    return create_artifact_digest(
        json.dumps(
            configuration.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    )


def create_run_manifest(configuration: StudyConfiguration) -> RunManifest:
    """Bind source, all visible requests and exact configuration to the journal.

    Args:
        configuration: Validated complete matrix, containing no credentials.

    Returns:
        Exact manifest required on every writer session and resume.
    """
    presentations = tuple(
        create_judge_request(
            row.prompt, row.generation, configuration.rubric
        ).model_dump(mode="json")
        for row in configuration.responses
    )
    return RunManifest(
        run=configuration.run,
        configuration_sha256=create_configuration_digest(configuration),
        source_sha256=configuration.source.source_sha256,
        assignments_sha256=create_artifact_digest(
            json.dumps(
                {
                    "assignments": [
                        item.model_dump(mode="json")
                        for item in configuration.assignments
                    ],
                    "presentations": presentations,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ),
        budget_plan=configuration.budget,
        model_routes=configuration.routes,
    )


def create_budget_draft() -> BudgetPlan:
    """Create the approved thirty-dollar allocation with explicitly unknown funding.

    Returns:
        Unconfirmed proposal, incapable of admitting any network reservation.
    """
    return BudgetPlan(
        identifier="approved-30-usd-allocation-v1-unfunded",
        confirmed=False,
        global_cap=30_000_000,
        arms=tuple(
            ArmCap(arm=arm, cap=cap)
            for arm, cap in (
                ("G1", 3_250_000),
                ("G27", 6_500_000),
                ("L8", 1_650_000),
                ("Q32", 9_750_000),
                ("paraphraser", 250_000),
                ("reviewer", 6_500_000),
                ("rewritten", 200_000),
            )
        ),
        funding=tuple(
            FundingCommitment(account=account, committed=None, usable_credit=0)
            for account in ("deepinfra", "huggingface")
        ),
        other_costs=None,
    )


def create_simulated_configuration(
    configuration: StudyConfiguration,
) -> StudyConfiguration:
    """Derive an explicitly synthetic freeze with scenario rates and no live gates.

    Args:
        configuration: Prepared source, fixed matrix and presentations.

    Returns:
        Separate synthetic run identity; no funding or execution claim is retained.
    """
    data = configuration.model_dump(mode="json")
    data.update(
        run=configuration.run + "-simulated",
        execution_mode="simulated",
        evidence_kind="synthetic",
    )
    data["gates"] = ExecutionGates().model_dump(mode="json")
    data["budget"] = BudgetPlan(
        identifier="synthetic-only-no-purchases",
        confirmed=True,
        global_cap=30_000_000,
        arms=configuration.budget.arms,
        funding=tuple(
            FundingCommitment(account=name, committed=0, usable_credit=0)
            for name in ("deepinfra", "huggingface")
        ),
        other_costs=0,
    ).model_dump(mode="json")
    data["prices"] = {
        role.value: TokenPrice(
            account=create_model_route(role).provider,
            confirmed=True,
            input_per_million=1,
            output_per_million=1,
        ).model_dump(mode="json")
        for role in JudgeRole
    }
    data["assignments"] = [
        RunAssignment(
            identifier=item.identifier,
            response_identifier=item.response_identifier,
            judge=item.judge,
            maximum_input_tokens=1000,
        ).model_dump(mode="json")
        for item in configuration.assignments
    ]
    return StudyConfiguration.model_validate(data)
