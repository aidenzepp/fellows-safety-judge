# fellows-safety-judge

Private starter repository for an Anthropic Fellows research project on LLM-as-judge safety evaluations.

The offline research workflow audits an explicit local Coin Flip CSV, freezes a complete four-judge matrix, journals synthetic attempts, and analyzes saved evidence. Live inference is held pending explicit source, token, price, funding, route/runtime and execution gates. No experiment results are claimed.

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
| NumPy | 2.5.4 | SVD for the supporting weighted additive fit. |
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

## Offline workflow

Every command reads explicit local paths. Nothing downloads source data, installs tokenizers, reads payment details, purchases credit or selects a live HTTP transport. Outputs use exclusive creation to preserve existing evidence.

Create the ignored local directories with `mkdir -p ./data ./runs`, then place the pinned source CSV at `./data/A_Coinflip_Judge_Data.csv`. The repository includes safe schema-valid inputs under `./examples/`; it includes no real source CSV or experiment results. Both `./data/` and `./runs/` are ignored by Git. Use fresh output names for a new run; existing evidence is never overwritten.

```bash
uv run python -m safety_judge --help
uv run python -m safety_judge audit --source ./data/A_Coinflip_Judge_Data.csv --output ./runs/audit.json
uv run python -m safety_judge prepare --source ./runs/audit.json --rubric ./examples/rubric.json --parameters ./examples/generation.json --run study-v1 --output ./runs/configuration.json
uv run python -m safety_judge mock-dry-run --configuration ./runs/configuration.json --frozen-output ./runs/synthetic.json --journal ./runs/synthetic.jsonl --output ./runs/synthetic-outcomes.json
uv run python -m safety_judge inspect --configuration ./runs/synthetic.json --journal ./runs/synthetic.jsonl --output ./runs/replay.json
uv run python -m safety_judge report --configuration ./runs/synthetic.json --journal ./runs/synthetic.jsonl --output ./runs/report.json --markdown ./runs/report.md
uv run python -m safety_judge estimate --assumptions ./examples/estimate-assumptions.json --output ./runs/estimate.json
```

`audit` retains source SHA-256, exclusions, original row identities, accepted component links, byte counts and the fixed pilot or an explicit no-go. Custom synthetic CSVs can supply `--component-links ./runs/edges.json` (a JSON array of two-string edges; `[]` means no cross-behavior edges). Default edges are the accepted source-specific whitelist, and an incompatible source fails rather than silently dropping links. No raw real source files belong in Git.

`examples/rubric.json` supplies the source-derived `coinflip-v2-derived-compliance-1` proposal with `version`, `text`, and `source` strings. Its source is paper §3.5; it is not a recovered historical model prompt. Preparing a configuration freezes its exact text and hash for that offline artifact. Explicit execution approval and the remaining live gates still apply. Generation JSON has `maximum_output_tokens`, `temperature`, and `timeout_seconds`; the approved real output allowance is 2048 tokens, and should not be reduced to fit cost. `examples/generation.json` preserves that allowance at temperature 0 with a 120-second timeout. Short synthetic fixtures can supply smaller bounds. Full rendered token counts and context compatibility remain unverified; source bytes are not token counts.

`prepare` records advertised routes, exact rubric/presentation/configuration hashes and every original/judge assignment. Funding, prices and input-token bounds remain unknown; every live gate starts closed. `mock-dry-run` saves a separate **synthetic** configuration with fake rates, fake credential values and a fixed ordinal response. It never constructs settings or accesses the network. Synthetic output proves mechanics only.

Reports retain explicitly supporting raw-row/equal-four weighting sensitivities and a complete-case item-adjusted additive fit with coverage/nonestimability limits. They retain pooled H1 as the sole primary, all four Holm-gated secondaries, all twelve exploratory judge-by-3/5/10-point rows, supporting coverage/valid-only accuracy and slices, and 1/5/10-percent boundary-adverse reference-error heuristics. Missing results remain assigned and unresolved. The production bootstrap uses 9,999 shared component draws; `--replicates` supports smaller synthetic fixtures, which do not certify tail power. Absent support, invalid replicates and zero variance produce explicit unavailable uncertainty. Selected-release and historical-model-identity limitations remain visible.

## Cost and runtime assumptions

`examples/estimate-assumptions.json` is ready for the `estimate` command. It uses the approved $30 allocation and 6,555 eligible originals, with all ten main/H2 route activities represented. Input/output token counts, ten-second latency and concurrency 16 are explicit **SCENARIOS**, not measurements or established quotas. The 8,192-token rewrite output is an illustrative scenario; actual rewrite limits must follow the frozen source-length/context rule. Existing-credit balances, new experiment purchase commitments and actual fees remain null, confirmation flags remain false, and human review time remains unknown. The example contains no keys and grants no spending or inference authority.

`estimate` consumes the `EstimateInputs` JSON schema in `safety_judge.estimation`. Supply `budget`, a complete `arms` array, `human_pause_hours` (number or null), `latency_verified` and `quotas_verified`. Each route assumption supplies:

- `arm`, exact `route`, `stage` (`main`, `rewrite`, `review`, `rewritten`), `calls`, and `attempts_per_call` (1 or 2).
- Complete `input_tokens_per_call`, `output_tokens_per_call`, and `tokens_verified`. Scenario values must be labeled false; no tokenizer census is implied.
- `price`: account, confirmation flag, input/output integer microdollars per million tokens; unknown rates are null.
- `mean_latency_seconds` and `requests_per_minute` (null if unknown), plus proposed `concurrent_calls`.

Include all four main routes (N each), 40 rewrites, 40 model pair reviews, and four rewritten-judge routes (40 each). All rewritten routes share one `rewritten` allocation. Main N is determined by the audited source, not a budget-driven sample. The accepted real source has 6,555 eligible originals, giving 26,220 main logical calls; H2 adds at most 240, and two attempts per logical call bounds total attempts at 52,920.

| Allocation | USD cap |
| --- | ---: |
| G1 main | 3.25 |
| G27 main | 6.50 |
| L8 main | 1.65 |
| Q32 main | 9.75 |
| H2 paraphraser | 0.25 |
| Sonnet paired review | 6.50 |
| All four rewritten judges combined | 0.20 |
| Fee/tax/FX allowance | 1.90 |
| All-in ceiling | 30.00 |

The $30 ceiling counts experiment-attributable costs. Each account funding record explicitly separates:

- `existing_credit`: general account balance explicitly excluded by the operator from experiment purchase costs; experiment usage paid from it counts at frozen rates. Null means unknown. This field never silently excludes a new purchase.
- `committed`: gross new experiment purchases, including their fees/taxes; the entire purchase counts even when partly unused. Null means unknown.
- `usable_credit`: remaining credit from those counted new purchases only. It cannot exceed `committed` or include existing credit.

For each account, attributable exposure is `committed + max(0, usage - usable_credit)`. Usage includes outstanding worst-case reservations until verified settlement. Existing credit never discounts that usage or expands per-arm caps. For example, $50 of existing DeepInfra credit with no new purchase contributes its experiment usage, not the unused $50. A new $5 Hugging Face purchase contributes the full $5, even if only $1 is consumed. With $20 DeepInfra usage and a retained $1.90 fee allowance, total exposure is $26.90. With the same purchase and allowance, DeepInfra usage above $23.10 breaches $30 even if its arm cap has room.

Count each fee once, either within the gross purchase or as another liability. The draft preserves unknown balances, new purchase commitments and actual fees. Estimates report existing credit, purchase commitments, gross usage, arm caps and attributable exposure separately. Missing attribution fields are rejected; old saved configurations require explicit attribution and liability reconciliation rather than silent migration. Existing reservations and settlements must be carried forward, never discarded. Changed funding facts invalidate resume under the same configuration identity. Unknown funding or rates produce unknown feasibility and block reservations. An estimate never enables execution.

Runtime is parameterized: each route takes approximately `calls * attempts * latency / concurrency`, also constrained by any supplied RPM ceiling. Independent routes take their maximum within each stage; main, rewrite, review and rewritten stages then sum. Shared account quotas, queues and tails can increase duration. Human review pause is separate and unknown unless supplied. At 6,555 calls, 16 concurrent requests and assumed 10/30/60-second latency, one route takes about 1.14/3.41/6.83 hours before retries. These are scenarios, not measurements or guaranteed forecasts. No inference benchmark has been run.

## Durable execution boundary

`runs.select_run` requires an explicit injected one-attempt transport and parsed settings; there is no live CLI command or default transport. The future live composition must confirm the exact account, gross funding, approved table, complete full-context token/rate bounds, route/runtime compatibility and explicit operator execution instruction. A spending-cap approval is insufficient.

The live boundary recomputes the frozen pre-call support screen and rejects failed support even if a caller sets the source-confirmation flag. The runner holds one exclusive journal writer session. It admits bounded windows of complete four-judge rows against every outstanding liability, persists every intent before dispatch, then saves raw bytes before parsing and terminal outcomes. Network workers never write files. Configurable global and per-provider limits bound in-flight work; defaults are conservative, not a promise of hours. Every append is flushed/fsynced. Failure poisons the writer; changed manifests or corrupt tails fail closed on resume. Interrupted intents remain occupied. Only independently certified non-delivery permits one retry; unknown delivery, refusals and malformed outputs do not. Ten consecutive transport failures stop new dispatch and remain latched on replay; already in-flight requests drain, with overshoot bounded by configured concurrency. Any prewritten but undispatched intents remain occupied and conservatively reserved. Missing or internally inconsistent reasoning usage retains full worst-case liability. Verified usage settles under frozen rates; over-bound usage pauses. Updated pricing requires reconciliation rather than route fallback.

## Exploratory H2 review

```bash
uv run python -m safety_judge review-requests --configuration ./runs/configuration.json --output ./runs/rewrite-requests.json
uv run python -m safety_judge review-presentations --cases ./runs/cases.json --output ./runs/paired-requests.json
uv run python -m safety_judge review-import --contract ./runs/review-contract.json --cases ./runs/cases.json --records ./runs/independent-reviews.json --main-report ./runs/main-report.json --output ./runs/fidelity.json
```

The owning `review` models define strict imported `ReviewContract`, `ReviewCase` and independently saved `ReviewRecord` schemas. Cases preserve rewritten text, frozen A/B presentation hashes and references to the four saved original judgments. Requests exclude released labels, evaluated judge outputs and the other reviewer's work. Neither model calls nor human annotation runs automatically. Exactly 40/40 pairs must pass both Sterling and the independent outside-family reviewer, and the saved main H1 decision must reject before rewritten judging is eligible. H2 stays entirely exploratory; no case replacement or automatic regeneration is allowed.

## Morning live checklist

1. Sterling supplies the two API keys through the untracked environment/settings boundary and identifies the intended DeepInfra and Hugging Face billing accounts.
2. Establish full rendered token bounds, current rates, route context/controls and actual quotas. Freeze exact source/rubric/templates and the complete all-four configuration.
3. Sterling alone performs any manual Ramp funding after checking balances, minimum purchases, gross fees/tax and the $30 all-in ceiling. Agents never handle card details or top-ups.
4. Record explicit execution authority, verify affordable reservations and hours-scale concurrency, then compose the live transport. No live inference is authorized by this README or the mock workflow.

## Layout

```text
examples/               safe rubric, generation and unfunded estimate inputs
data/                   ignored local source CSVs
runs/                   ignored local manifests, journals and generated reports
src/safety_judge/       source, judging, budget, artifacts, model access, runner,
                        review, finite analysis, inference, reporting and estimation
tests/                  one test module per module plus naming-policy checks
tools/setup-vivi.sh     pinned Vivi mailspace bootstrap
.agents/skills/         reusable conventions and pinned coordination skills
```

`pyproject.toml` remains the source of truth for tooling and policy. `.vivi/` is local coordination state and is never committed. `tools/setup-vivi.sh` initializes the mailspace and vendored skills using `VIVI_VERSION`; it does not seed experiment work.


The preregistered `outer-markdown-fence-v1` rule strips surrounding whitespace, then removes at most one whole outer Markdown fence before the unchanged strict JSON parser. The opening line has at least three identical backticks or tildes, optional horizontal whitespace and one optional language tag containing neither whitespace nor fence characters; it ends in LF or CRLF. The closing line uses the same character at least as many times, with optional horizontal whitespace. Interior text and line endings stay unchanged. Inline, unmatched or mixed fences are not stripped; nested/multiple fences, prose, duplicate keys, extra fields, coercion and invalid JSON still fail. Refusal, truncation and unknown delivery retain precedence. No recursive stripping or repair occurs.

Historical raw journals and their saved terminal outcomes remain immutable. Newly parsed attempts use the same frozen normalization at the shared `create_terminal_outcome` boundary for every judge; `create_strict_terminal_outcome` retains the unchanged raw decoder. `create_saved_normalized_outcomes` derives versioned paired raw/normalized outcomes for every intended attempt, including unknowns. `create_normalization_coverage` reports both validity counts and rates with the same assigned denominator. These paired sidecars are separate from historical strict report inputs: a future main report must explicitly choose the frozen normalized outcomes and publish the raw strict sensitivity, without silently changing an old report or configuration.

Original first-smoke responses remain the canonical main candidates under this rule. The separately authorized repeat is diagnostic only; it never replaces an original based on validity or label and never adds an independent main observation. Both raw sets and paired outcomes are preserved. Repeat admission includes original settled costs and all unknown liabilities against the cumulative ten-cent smoke total and original arm subcaps. No main or H2 execution is implied.
