"""Shared fixtures that keep tests independent of the machine they run on."""

import os

import pytest

from safety_judge.settings import ENVIRONMENT_VARIABLE_PREFIX


@pytest.fixture(autouse=True)
def remove_inherited_safety_judge_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ``SAFETY_JUDGE_*`` variables a developer or CI runner already exports.

    Without this, a variable set in the host shell would silently change which
    value a settings test observes. ``monkeypatch`` restores them afterwards.
    """
    for variable_name in tuple(os.environ):
        if variable_name.upper().startswith(ENVIRONMENT_VARIABLE_PREFIX):
            monkeypatch.delenv(variable_name)
