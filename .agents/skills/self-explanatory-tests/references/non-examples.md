# Testing Non-Examples

These patterns create green tests without trustworthy evidence or failures without enough context to repair them.

## Opaque Failure Messages

```python
try:
    settings = select_application_settings(environment_file_path=path)
except Exception:
    pytest.fail("failed")

exit_status = update_command_run(arguments)
captured = capsys.readouterr()
assert exit_status == 0
assert settings.logging_level
```

Problems:

- `pytest.fail("failed")` does not name the assumption or operation. It catches every exception only to report a message that says nothing; let the exception propagate, or catch the specific error and state which assumption broke.
- the status assertion discards the stdout and stderr that would explain the failure. `readouterr()` already consumed them, so pytest prints only `assert 2 == 0` and the text that explains the status never reaches the report.
- `assert settings.logging_level` can never fail, because every `LoggingLevel` member is a non-empty string and therefore truthy. It names no contract and passes for any value.

## Testing the Implementation Path

```python
def test_loading_settings_builds_the_settings_class_once(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr("safety_judge.settings.ApplicationSettings", constructor)

    select_application_settings(environment_file_path=None)

    constructor.assert_called_once_with(_env_file=None)
```

This freezes one call and its keyword name, not the returned settings contract. It can fail after a harmless refactor of how the loader builds the model, and it passes even if the loader stops validating anything. A `MagicMock` also accepts any attribute and any call, so a stale mock keeps passing after the real method disappears. Prefer loading real settings from `monkeypatch.setenv` or a `tmp_path` file and asserting the returned values.

## Tests as the Only Invariant

```python
def create_verdict(score: float) -> Verdict:
    assert 0.0 <= score <= 1.0, "score must lie between 0 and 1"
    ...
```

If every caller and test must remember that `score` lies between 0 and 1, the invariant has no owner. The `assert` is also runtime validation, which production code in this repository does not use, and Python skips it entirely under `-O`. Prefer a trusted `ConfidenceScore` created at the boundary, then test its construction and preservation.

## Dependency-Injection Container

```python
def select_overdue_reports(context: ServiceContainer) -> list[Report]:
    clock = context.resolve_clock()
    repository = context.resolve_repository()
    client = context.resolve_http_client()
    ...
```

The real dependencies and required capabilities are hidden behind a generic bag. Pass the narrow values or capabilities explicitly and wire them at the composition boundary.

## Protocol per Class

```python
class UserRepositoryLike(Protocol):
    def select_user(self, identifier: UserIdentifier) -> User | None: ...
```

A `Protocol` is not automatically useful because a concrete `UserRepository` exists. Add the seam when the consumer needs a stable capability, legitimate substitution, or ownership boundary, not merely so a mocking library can replace every class.

## Convenient Fake, Different System

An in-memory repository that silently allows duplicate keys while production rejects them is not faithful evidence. Run shared contract tests against both implementations, for example through a parametrized fixture, or use the real repository hermetically.

## Broad Scenario Test

```python
def test_account_workflow_works() -> None:
    # creates an account, changes permissions, imports data, retries a timeout,
    # exports a report, and checks six unrelated outcomes
    ...
```

One failure cannot identify which promise broke. Split independent behaviors while keeping each complete contract together.

## Invented Behavior

```python
def test_retries_exactly_three_times() -> None:
    # No user requirement, public contract, or existing behavior establishes 3.
    ...
```

Do not turn an implementation guess into a permanent requirement. Find ground truth first.

## False Red

```text
RED: ERROR at setup of test_a_misspelled_setting_is_rejected
     fixture 'envirnoment_file_path' not found
```

That does not prove the behavior is missing or broken. RED is valid only when the test runs far enough to fail on the intended contract and pytest reports `FAILED`. An `ERROR` at collection or at setup, an `ImportError`, a `NameError`, or a `TypeError` from a misspelled helper says the test could not run.

## Hidden Machine State

```python
settings = select_application_settings()
home_settings = Path.home().joinpath(".config", "safety_judge.env").read_text()
```

The first call reads whatever `.env` sits in the directory pytest was started from, which may be a developer's real file with real secrets. The second reads one person's home directory. Both make the test depend on one machine. Pass `environment_file_path=None` or a file under `tmp_path`, and let `tests/conftest.py` and `monkeypatch` own the process environment.

## Policy Bypass

```python
@pytest.mark.filterwarnings("ignore")
def test_parses_the_fixture() -> None:
    ...
```

Also reject these bypasses:

- lowering a ruff rule or widening `per-file-ignores` for `tests/**` because a test is inconvenient
- loosening `filterwarnings = ["error"]`, `xfail_strict`, `--strict-markers`, or `--strict-config`
- a bare `# noqa`, or a `# pyright: ignore` that names no rule and gives no reason
- running ruff or pyright on `src/` only so `tests/` escapes the policy
- moving production logic into `tests/` solely to escape production policy such as S101

A rule-named `# pyright: ignore[rule]` with a stated reason is acceptable only where the test deliberately violates a type to prove a runtime guard, as `test_context_rejects_mutation` in `tests/test_errors.py` does. If the rule itself is genuinely wrong, change the policy in `pyproject.toml` deliberately, as its own reviewed change.

## Over-Abstracted Setup

```python
def test_the_overdue_report_includes_the_account(
    standard_context: StandardContext,
) -> None:
    ...
```

If the tested outcome depends on identity, permissions, time, or stored rows hidden inside the `standard_context` fixture, the reader cannot see why the result should occur. Prefer DAMP setup that names contract-bearing facts directly. An autouse fixture such as `remove_inherited_safety_judge_variables` is acceptable because it removes ambient state rather than adding scenario facts; each test still states the values that matter with `monkeypatch.setenv`.

## Common Rationalizations

| Rationalization | Reality |
| --- | --- |
| "The test passes." | A passing test can still protect the wrong behavior or only agree with its mock. |
| "Mocking is easier." | Easier setup is not better evidence; try a real local dependency, `tmp_path`, a fake, a fixture, or a stub first. |
| "Dependency injection means a Protocol per class." | Inject the smallest controlled value or capability; keep concrete code when abstraction adds no honest seam. |
| "The test checks the invariant." | A test detects violations after the fact; the design should prevent or reject invalid states at their owner boundary. |
| "It is just a private helper." | Private decomposition is replaceable unless that helper embodies the stable contract. |
| "The error is already printed." | Future readers still need the failed operation and assumption that made the source error relevant. |
| "The test is obvious to me." | The failure must remain self-explanatory to an agent that did not author it. |
| "I can rerun until it passes." | Intermittent success is evidence of nondeterminism, not correctness. |
