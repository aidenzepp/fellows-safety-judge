# Testing Sources

These sources explain the reasoning behind the repository policy. Use them when a test boundary, failure-message rule, dependency choice, or lint exception is disputed.

## Source Skills Adapted

- `contract-tests`: name the contract before RED, ground expected behavior, choose the smallest stable boundary, prefer observable outcomes, resist mocks, and run a refactor-survival check.
- `error-messages`: treat failures as developer-facing errors that identify what happened, why it matters, relevant context, and useful next evidence.
- `root-cause`: reproduce the symptom and protect the deepest violated promise rather than the first visible symptom.
- `red-green`: prove RED fails for the intended reason, classify failures honestly, and never report unexecuted tests as successful.
- `fool-proof-software`: remove hidden memory requirements from fixtures and make invalid setup fail at the earliest useful boundary.
- `software-taste`: make invalid states difficult to represent, parse once at honest boundaries, inject dependencies without ceremony, and test observable contracts.
- `designing-trustworthy-functions-and-data`: keep production contracts, dependencies, effects, invariants, and abstraction boundaries truthful while resisting mock-driven or type-driven over-design.

The repo-owned skill adapts these principles to Python and pytest and this repository's lint policy; it does not import the source skills' broader workflows.

## Python and pytest Mechanics

- [pytest: Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) — recommends a `src` layout with tests in a separate directory, running tests against an installed or editable install of the package, and `--import-mode=importlib` for new projects; also documents strict mode.
- [pytest: pytest import mechanisms and `sys.path`](https://docs.pytest.org/en/stable/explanation/pythonpath.html) — explains the import modes; `importlib` mode leaves `sys.path` alone and does not require unique test module names, but test modules cannot import each other, so shared fixtures belong in `conftest.py`.
- [pytest: How to use fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html) — documents fixtures, autouse fixtures, factories as fixtures, parametrized fixtures, and `conftest.py` sharing.
- [pytest: How to parametrize fixtures and test functions](https://docs.pytest.org/en/stable/how-to/parametrize.html) — documents `pytest.mark.parametrize` and the `ids` that name each case in a report.
- [pytest: How to monkeypatch and mock modules and environments](https://docs.pytest.org/en/stable/how-to/monkeypatch.html) — documents `setenv`, `delenv`, and `setattr`, and that every modification is undone when the test ends.
- [pytest: How to use temporary directories and files in tests](https://docs.pytest.org/en/stable/how-to/tmp_path.html) — documents `tmp_path`, a temporary directory unique to each test function.
- [pytest: How to write and report assertions in tests](https://docs.pytest.org/en/stable/how-to/assert.html) — documents assertion introspection, `pytest.raises` with `match`, and inspecting the exception through `excinfo`.
- [pytest: How to capture warnings](https://docs.pytest.org/en/stable/how-to/capture-warnings.html) — documents `filterwarnings = error` to turn warnings into failures and `pytest.warns` to assert an expected warning.
- [Ruff: flake8-pytest-style rules (`PT`)](https://docs.astral.sh/ruff/rules/#flake8-pytest-style-pt) — documents the pytest style checks that ruff enforces under `select = ["ALL"]`.
- [Ruff: `lint.per-file-ignores`](https://docs.astral.sh/ruff/settings/#lint_per-file-ignores) — defines the per-file rule exceptions used for `tests/**` in `pyproject.toml`.
- [Python Language Reference: The `assert` statement](https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement) — states that no code is emitted for `assert` when optimization is requested, which is why it is not runtime validation.

## Contract Quality

- [Google Testing Blog: Test Behavior, Not Implementation](https://testing.googleblog.com/2013/08/testing-on-toilet-test-behavior-not.html) — tests should normally survive behavior-preserving implementation changes.
- [Google Testing Blog: Test Behaviors, Not Methods](https://testing.googleblog.com/2014/04/testing-on-toilet-test-behaviors-not.html) — behavior concepts, rather than one test per method, determine useful test boundaries.
- [Google Testing Blog: Don't Overuse Mocks](https://testing.googleblog.com/2013/05/testing-on-toilet-dont-overuse-mocks.html) — interaction-heavy mocks leak implementation details and provide weaker evidence than real or hermetic alternatives.
- [Google Testing Blog: Increase Test Fidelity by Avoiding Mocks](https://testing.googleblog.com/2024/02/increase-test-fidelity-by-avoiding-mocks.html) — choose the highest-fidelity dependency that remains appropriate for the test's size and determinism constraints.
- [Addy Osmani: Test-Driven Development Skill](https://github.com/addyosmani/agent-skills/blob/main/skills/test-driven-development/SKILL.md) — source for the prove-it regression pattern, DAMP tests, behavior-sized cases, and common testing rationalizations.

## Design and Dependency Boundaries

- [Alexis King: Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/) — argues for turning weakly typed input into a trusted type once, at the boundary, so later code cannot receive an invalid value.
- [Python typing specification: Protocols](https://typing.python.org/en/latest/spec/protocol.html) — defines structural subtyping, which lets a consumer own a small capability that both the real adapter and a fake satisfy without inheriting from it.
- [Martin Fowler: Inversion of Control Containers and the Dependency Injection Pattern](https://martinfowler.com/articles/injection.html) — distinguishes dependency injection from service location and emphasizes separating configuration from use.
