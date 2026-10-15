# fellows-safety-judge

Private starter repository for an Anthropic Fellows research project on LLM-as-judge safety evaluations.

This is a skeleton. It contains structure, tooling, typed settings, an error hierarchy, agent instructions, and a demo module. It deliberately contains no judge logic, prompts, datasets, or model calls; those are designed later.

## Quick start

Install [uv](https://docs.astral.sh/uv/) 0.13.1 or newer, then:

```bash
uv sync                      # creates .venv with the pinned CPython and locked dependencies
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
uv run prek install          # git hooks, once per clone
tools/setup-vivi.sh          # local agent mailspace, once per clone
```

`uv run ruff format` and `uv run ruff check --fix` repair what they can. CI runs the four checks above plus shellcheck on the bootstrap script.

## Tool choices

| Tool | Version | Why |
| --- | --- | --- |
| CPython | 3.15.0 | The latest stable release (see below). |
| uv | 0.13.1 | Project, environment, lockfile, and interpreter management in one tool; `uv_build` 0.13.1 is the build backend. |
| pyright | 1.1.414 | Type checker in `strict` mode plus extra rules (see below). |
| ruff | 0.17.0 | Formatter and linter with every rule selected (`ALL`) minus three commented ignores. |
| pytest | 9.1.1 | Test runner, configured in native `[tool.pytest]` TOML with warnings as errors. |
| pydantic | 2.14.1 | Immutable, validated data models. |
| pydantic-settings | 2.16.0 | Typed settings from environment variables and `.env`. |
| prek | 0.5.5 | Git hook runner; reads standard pre-commit config, so `pre-commit` also works. |
| shellcheck-py | 0.11.0.1 | ShellCheck 0.11.0 as a dev dependency, so local runs and CI use the same version. |
| vivi | v12.0.4 | Local-first mailspace CLI for coordinating agents; pinned in `VIVI_VERSION`. |
| pre-commit-hooks | v6.0.0 | File hygiene hooks. |
| conventional-pre-commit | v4.4.0 | Rejects commit messages that are not Conventional Commits. |
| actions/checkout, astral-sh/setup-uv | v7.0.1, v10.3.0 | Pinned to commit SHAs in CI. |

Dev tools are pinned exactly in `pyproject.toml`; every pin was the latest release when this repository was created. Runtime dependencies carry a lower bound and `uv.lock` pins them. Upgrading a tool is its own commit that also fixes whatever the new version reports.

## Python version

`.python-version` pins **CPython 3.15.0**, released on 2026-10-09 (checked on [python.org](https://www.python.org/downloads/release/python-3150/), on endoflife.date, which lists it as the latest 3.15 release with bugfix support until 2028-10-09, and with `uv python list`, which offers `cpython-3.15.0`). 3.16 exists only as `3.16.0a1`; its final release is scheduled for 2027-10-05 (PEP 826). The newest stable release gives the longest support window and the newest language features. This code uses PEP 810 explicit lazy imports (`lazy from ... import ...`) for typing-only imports, PEP 695 `type` aliases, and PEP 649 lazy annotations, so `requires-python` is `>=3.15,<3.16`. uv is set to `python-preference = "only-managed"` so every clone runs the same interpreter. pydantic-core, the only compiled runtime dependency, ships cp315 wheels.

## Type checker

pyright runs in `strict` mode and gates CI. On top of strict it enables `reportImplicitOverride`, `reportImportCycles`, `reportMissingSuperCall`, `reportPropertyTypeMismatch`, `reportUninitializedInstanceVariable`, `reportUnnecessaryTypeIgnoreComment`, `reportCallInDefaultInitializer`, and `reportUnusedCallResult`. `# type: ignore` is disabled; the only suppression is `# pyright: ignore[rule]`, and pyright reports one that is no longer needed.

The alternatives were run on this repository's code, not only read about:

| Checker | Version | PyPI status | On this repo | Typing conformance suite, automated pass |
| --- | --- | --- | --- | --- |
| pyright | 1.1.414 | Production/Stable | 0 errors (the gate) | 131 of 146 (1.1.410) |
| mypy `--strict` | 2.4.0 | Production/Stable | 2 errors, both lines suppressed with `# pyright: ignore` | 82 of 146 (2.1.0) |
| Pyrefly | 1.3.2 | Production/Stable | 3 errors: the same 2, plus a `bad-override` on `ApplicationSettings.__init__` | 139 of 146 (1.3.0-dev.1) |
| ty | 0.0.87 | Beta | 4 errors: the same 2, the override, and a false positive on `pending_classes.extend(error_class.__subclasses__())` | 133 of 146 (0.0.83) |

Conformance counts come from `conformance/results` in [python/typing](https://github.com/python/typing); the versions in parentheses are the versions that produced them. They measure agreement with the typing specification, not strictness or ecosystem fit.

pyright is the gate because its strictness is a set of independently selectable named rules, because `enableTypeIgnoreComments = false` with `reportUnnecessaryTypeIgnoreComment` makes every suppression name its rule and expire when it stops being needed, and because it understands pydantic through `dataclass_transform` without a plugin. ty is still Beta and already reports a false positive on valid code. Pyrefly is a credible second opinion. Re-run `uvx ty check` and `uvx pyrefly check` when either changes its status; neither is wired into CI.

## Layout

```text
src/safety_judge/       package: errors.py, settings.py, example_text_label.py (demo)
tests/                  one test module per module, plus a naming-convention test
tools/setup-vivi.sh     vivi bootstrap
.agents/skills/         agent skills; CLAUDE.md is a symlink to AGENTS.md
.github/workflows/      CI
.pre-commit-config.yaml hooks
VIVI_VERSION            the single place the vivi pin lives
```

`AGENTS.md` holds the conventions: the function-name verb vocabulary, the error hierarchy, configuration, documentation, and test rules.

## Mailspace (vivi)

`.vivi/` is local state and is gitignored. `tools/setup-vivi.sh` installs vivi v12.0.4 (or confirms the installed version matches `VIVI_VERSION`), runs `vivi mailspace init`, adds the roles `mind`, `hand`, `auditor`, and `operator` with the same-named kinds, and refreshes the vendored skills in `.agents/skills`. It is idempotent and creates no tasks, needs, or other work items. To bump vivi, edit `VIVI_VERSION`, rerun the script, and commit the skill changes.

## Deleting the demo module

`example_text_label.py` and `tests/test_example_text_label.py` demonstrate the conventions and are not part of the project. Delete both once real modules exist. A few skill examples cite the module (`grep -rn example_text_label .agents`); update them in the same commit.

## Known gaps and decisions

- **Private-helper docstrings are not lint-enforced.** Ruff's `D1xx` rules skip underscore-private names, and nothing checks constants or aliases. The `document-code` skill requires them; review enforces it.
- **`BaseSettings` immutability is runtime-only.** Pyright rejects `frozen` as a class keyword on a `BaseSettings` subclass, so `ApplicationSettings` sets it in `model_config`.
- **The docstring format differs from the owner's templates.** The templates require multi-line JSDoc even for one sentence. Ruff's `D200` requires the opposite for docstrings, so one sentence stays on one line.
- **Ruff's pydoclint rules are preview rules in 0.17.0.** `DOC201`, `DOC202`, `DOC402`, `DOC403`, `DOC501`, and `DOC502` are enabled by exact code through `explicit-preview-rules`; no other preview rule is on.
- **The vivi installer is fetched from `main`.** The binary version is pinned, but the installer script is not. The copy at the `v12.0.4` tag is byte-identical today, so the URL can be pinned to the tag.
- **`auditor` is not a named vivi kind.** `vivi role add --help` lists hand, head, mind, operator, steward, or freeform; `auditor` is accepted as freeform.
- **No coverage threshold, randomized test order, or parallel test runner.** There is no experiment code to measure; add them when there is.
- **The template repositories were not readable on GitHub.** The skills and `AGENTS.md` conventions come from the supplied archive, which contains no vivi wiring, so the bootstrap follows vivi's own `--help`.
