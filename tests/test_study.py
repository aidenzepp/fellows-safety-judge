"""Prepared monetary authority remains explicitly unfunded."""

from safety_judge.study import ExecutionGates, create_budget_draft


def test_approved_allocations_plus_fee_allowance_equal_thirty_dollars() -> None:
    draft = create_budget_draft()
    assert sum(arm.cap for arm in draft.arms) + 1_900_000 == draft.global_cap
    assert not draft.confirmed
    assert draft.other_costs is None
    assert [fund.existing_credit for fund in draft.funding] == [None, None]
    assert [fund.committed for fund in draft.funding] == [None, None]
    assert not any(ExecutionGates().model_dump().values())
