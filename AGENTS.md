# fellows-safety-judge - agent notes

Skeleton for an Anthropic Fellows research project on LLM-as-judge safety evaluations. It is intentionally free of experiment code: no judge logic, prompts, datasets, or model calls. Add those only when the owner asks, and design them deliberately. `src/safety_judge/example_text_label.py` and its test are a demo of the conventions; delete them when real modules exist.

## Policy

`pyproject.toml` is the source of truth for uv, ruff, pyright, and pytest. `README.md` records why each tool was chosen.

- Fix code instead of weakening policy. Do not change rule selection, ignores, or the pyright mode, and do not skip verification targets, without explicit approval.
- Suppress a diagnostic only at one line, with the rule named and a reason: `# noqa: RULE -- reason` or `# pyright: ignore[rule] -- reason`. A bare `# noqa` is a lint error, `# type: ignore` suppresses nothing because pyright is configured to ignore it, and both tools report a suppression that is no longer needed.
- Treat warnings as design feedback. They may remain while exploring, but resolve them before calling work complete.
- Tools are pinned exactly in `pyproject.toml`. Upgrading one is its own commit that also fixes whatever it newly reports.
- Give private production items the same documentation scrutiny as public items. Tests may omit callable-contract documentation, but they remain subject to production correctness rules.

If a rule appears inappropriate, explain the failing rule, why changing the code would be worse, the smallest policy change, and its consequences. Change the policy only after approval.

## Workflow

Run `uv sync` once, then before completion:

```bash
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

`uv run ruff format` and `uv run ruff check --fix` repair what they can. `uv run prek install` installs the git hooks once per clone: fixers and lint at commit, Conventional Commits at commit-msg, pyright and pytest at push. CI runs the four commands above plus shellcheck on `tools/setup-vivi.sh`.

`.python-version` pins the exact CPython; uv installs only managed interpreters. Change dependencies with `uv add` or `uv add --dev` and commit `uv.lock`; never edit it by hand.

## Structure

- `src/safety_judge/` is the package. `errors.py` is the error hierarchy, `settings.py` is the typed configuration, and `py.typed` marks the package as typed.
- `tests/` mirrors the package: one `test_<module>.py` per module, shared fixtures in `conftest.py`. Do not add `__init__.py` files under `tests/`; pytest imports by path.
- `.env.example` documents every setting without secrets. A test keeps it in step with `ApplicationSettings`.
- `tools/` holds repository scripts. `VIVI_VERSION` pins the vivi release.

Use absolute imports. Do not re-export through `__init__.py`. Put typing-only imports under `lazy from ... import ...` (Python 3.15), as `errors.py` does; ruff enforces this.

## Naming

Names are long, explicit, and descriptive. Do not abbreviate.

Every module-level function starts with one of seven verbs; `tests/test_naming_conventions.py` enforces it:

| Verb | Meaning |
| --- | --- |
| `select`, `insert`, `update`, `delete`, `rename` | I/O against a store or the environment: a file, database, network, environment variable, the clock, or a random source |
| `create`, `remove` | In-memory construction or derivation from the arguments |

A function that mixes both usually splits into an edge (`select_`, `insert_`) and a core (`create_`, `remove_`). The verb is a promise about the body: a `create_` function must not read the clock or the environment. Methods follow the same vocabulary where practical. Classes are nouns, and `test_*` functions are full sentences.

## Errors

Raise subclasses of `SafetyJudgeError` for deliberate failures: a stable `code`, a message that says what failed and what to do next, and read-only `context` facts. Chain with `raise ... from cause`. Never raise bare `Exception`, and never use `assert` to validate runtime input outside tests. Absence is `X | None`; failure is an exception.

Add a subclass only when a caller needs to branch on it. List it in the hierarchy tree in `errors.py` and in the inventory in `tests/test_errors.py`.

## Configuration

`ApplicationSettings` (pydantic-settings, prefix `SAFETY_JUDGE_`) is the only reader of the environment; `select_application_settings` is the boundary. Everything else receives the parsed settings. Add a setting by adding a field, documenting it in `.env.example`, and testing it. Secrets use `SecretStr` and live only in an untracked `.env`.

Data models are pydantic `BaseModel` subclasses declared `frozen=True, extra="forbid"` as class keywords. `BaseSettings` cannot take `frozen` as a class keyword under pyright, so its immutability comes from `model_config` and is enforced at runtime only.

## Documentation

Google-style docstrings on every function, method, class, `type` alias, and `Final` constant, private helpers included. Ruff enforces public docstrings and complete `Args`, `Returns`, and `Raises` sections; it does not check private helpers, constants, or aliases, so review does. Comments explain a constraint, trade-off, or reason, never what the code does.

## Tests

pytest, function-style, named as sentences. Prefer fakes and `monkeypatch` at documented seams over `unittest.mock`. `tests/conftest.py` removes inherited `SAFETY_JUDGE_*` variables so a developer's environment never leaks into a run. Warnings are errors.

## Mailspace

`vivi` is the local-first mailspace for coordinating agents. `.vivi/` is local state and is never committed. After cloning, run `tools/setup-vivi.sh`: it installs or verifies the release pinned in `VIVI_VERSION`, initializes `.vivi/`, adds the roles `mind`, `hand`, `auditor`, and `operator`, and refreshes the vendored vivi skills. Change the pin only in `VIVI_VERSION`, then rerun the script and commit the skill changes.

- Run `vivi boot` first to orient, then `vivi board` for open work.
- A `task` is work assigned now, with an owner and a done condition. A `need` is must-do-soon work awaiting assignment. Both bodies need a line that begins `done_when:` or `vivi step` will not dispatch them.
- Do not create tasks, needs, wants, or mail unless asked. The seeded mailspace is empty on purpose.

## Skills

- `.agents/skills/conventional-commits`: commit decisions, boundaries, staging, and messages.
- `.agents/skills/document-code`: docstrings for functions, classes, models, aliases, and constants, and capturing non-obvious constraints.
- `.agents/skills/type-design`: data models, identifiers, state unions, absence, and boundary types.
- `.agents/skills/function-decomposition`: when to extract, inline, or name a function.
- `.agents/skills/designing-trustworthy-functions-and-data`: honest signatures, effects, parsing at boundaries, invariants, and abstraction levels.
- `.agents/skills/self-explanatory-tests`: test design, organization, failure messages, and debugging.
- `.agents/skills/error-messages`: caller-facing errors, API and CLI error payloads, and messages that tell someone what to do.
- `.agents/skills/vivi`: the vivi CLI reference. `tugboat` and `speedboat` are operating protocols the operator chooses between; read one only when asked to run that protocol.

## Skills policy

Keep only broadly reusable foundation skills here; project-specific skills belong with the project that needs them. `vivi`, `tugboat`, and `speedboat` are byte-for-byte copies of the pinned release, written by `vivi skills install`. Do not edit them, and exclude them from linters and fixers.
