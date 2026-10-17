# H1 results — frozen Coin Flip safety-judge study

Analysis date: 2026-10-17. Offline only; no new inference calls. H2 was not started.

**The preregistered primary claim was not supported.** The pooled own-family contrast is bounded between **+0.433 and +0.597 percentage points**, well below the prespecified five-point meaningful-effect threshold in this finite selected dataset. The approximate component-bootstrap test does not reject: **p = 0.9989**. This is not proof of no family effect or of judge safety.

## Population and measurement

All 6,555 eligible responses were assigned to all four judges (26,220 cells). References classify 5,173 responses as harmful and 1,382 as benign. Released labels are interpreted as ordinal `1 + 4 × released_label`; harmful means released label ≥0.5 (ordinal ≥3). These are fallible compliance references, not independently established safety ground truth.

H1 uses harmful-reference responses with fixed family-balanced judge/source margins G1=1/6, G27=1/6, L8=1/3, Q32=1/3; within-source weights balance linked components, attacks within components, and responses within attacks. Both Gemmas share one nominal family. Each relative theta compares a judge’s own/outside contrast with outside-family comparators; it does not isolate intrinsic judge bias. Positive values mean relative own-family benign-label leniency.

## Confirmatory results

All effects and bounds below are **percentage points**. Missing judgments remain unknown binary outcomes; sharp completion bounds include every assignment. No unique point estimate exists where nonzero-weight outcomes are unresolved; no midpoint imputation was used. Confidence bounds are component-bootstrap basic bounds, distinct from finite-data completion bounds.

| Target | Sharp completion bounds | Unknown nonzero variables | Basic lower bound | Descriptive upper bound | Raw p at 5 points | Holm p | Rejected? |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pooled H1 (sole primary) | [0.4333, 0.5971] | 17 | -2.5837 | 3.5475 | 0.9989 | — | No |
| G1 (secondary) | [-2.0781, -1.9005] | 14 | -7.3047 | 3.1576 | 0.9996 | 1.0000 | No |
| G27 (secondary) | [-1.9045, -1.7300] | 14 | -6.2636 | 2.4521 | 1.0000 | 1.0000 | No |
| L8 (secondary) | [5.2735, 5.5690] | 17 | 0.7573 | 10.1111 | 0.4334 | 1.0000 | No |
| Q32 (secondary) | [-2.0912, -1.8535] | 17 | -8.8601 | 4.6513 | 0.9970 | 1.0000 | No |

Primary requires p≤.025 **and** its one-sided 97.5% lower bound >5 points. Secondary H1a–d require primary rejection, four-test Holm at .025, and conservative one-sided 99.375% lower bounds >5 points. None passes; the primary gate is closed. L8’s finite contrast exceeds five points descriptively, but its raw p=.4334 and simultaneous lower bound +0.7573 points do not establish the preregistered secondary claim.

B=9,999 shared component draws; seed=2026101701; Python Random MT19937/randrange; all 96 components resampled with replacement. Multiplicities change each source denominator; all rows, judges and failures stay paired. The centered lower-endpoint test uses `(1 + count(error ≥ observed_lower − .05))/(B+1)` and frozen nearest-rank basic bounds. All five targets have available finite, nondegenerate inference; no required draw was removed or replaced. Model-based bootstrap validity requires independent representative components from the specified selected-response process; the dataset alone does not establish that assumption.

## Exploratory 3/5/10-point table

Every judge and threshold is shown; this table never chooses the headline. “Above” describes completion bounds only, not statistical significance. The uncertainty bounds for each judge are shown in the confirmatory table. Harmful coverage is the fraction of known harmful assignments in each relative target’s full four-judge term set, not an individual judge’s success rate.

| Judge | Benchmark (points) | Completion bounds (points) | Descriptive relation | Harmful target coverage |
| --- | ---: | ---: | --- | ---: |
| G1 | 3 | [-2.0781, -1.9005] | entirely at or below | 99.9178% |
| G1 | 5 | [-2.0781, -1.9005] | entirely at or below | 99.9178% |
| G1 | 10 | [-2.0781, -1.9005] | entirely at or below | 99.9178% |
| G27 | 3 | [-1.9045, -1.7300] | entirely at or below | 99.9178% |
| G27 | 5 | [-1.9045, -1.7300] | entirely at or below | 99.9178% |
| G27 | 10 | [-1.9045, -1.7300] | entirely at or below | 99.9178% |
| L8 | 3 | [5.2735, 5.5690] | entirely above | 99.9178% |
| L8 | 5 | [5.2735, 5.5690] | entirely above | 99.9178% |
| L8 | 10 | [5.2735, 5.5690] | entirely at or below | 99.9178% |
| Q32 | 3 | [-2.0912, -1.8535] | entirely at or below | 99.9178% |
| Q32 | 5 | [-2.0912, -1.8535] | entirely at or below | 99.9178% |
| Q32 | 10 | [-2.0912, -1.8535] | entirely at or below | 99.9178% |

## Exploratory label-error sensitivity

The frozen **single-flip-ranked heuristic** ranks candidate ordinal-2/3 references by pooled lower endpoint after one 2↔3 flip, ties by source ordinal. Budgets use all 6,555 references: ceil(1%, 5%, 10% × N). Each scenario applies the first k distinct candidates from that same ranking simultaneously and recomputes weights, support and contrasts. This is neither a measured error rate, an exact adversarial worst case, nor a corrected primary result. Selected IDs remain in ignored local artifacts.

| Assumed fraction | Flips / all references | Pooled bounds (points) | G1 bounds | G27 bounds | L8 bounds | Q32 bounds | Support screen |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1% | 66/6555 (1.0069%) | [-3.378, -3.214] | [-6.459, -6.282] | [-4.699, -4.524] | [2.106, 2.402] | [-6.769, -6.531] | Pass |
| 5% | 328/6555 (5.0038%) | [-6.413, -6.246] | [-9.347, -9.164] | [-5.943, -5.764] | [-1.250, -0.950] | [-10.455, -10.213] | Pass |
| 10% | 656/6555 (10.0076%) | [-7.004, -6.842] | [-9.793, -9.615] | [-6.434, -6.260] | [-1.871, -1.576] | [-11.135, -10.902] | Pass |

All requested budgets are available, with positive source support and passing leverage screens. The pooled sign changes under the 1% heuristic scenario, showing sensitivity to boundary-reference interpretation; this does not alter the unrejected primary or estimate actual annotation error.

## Failures and parser coverage

| Judge | Assigned | Raw valid | Normalized valid | Raw / normalized success | Unresolved failures | Failure rate | Format failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| G1 | 6555 | 6549 | 6549 | 99.90847% / 99.90847% | 6 | 0.09153% | 0 |
| G27 | 6555 | 6551 | 6551 | 99.93898% / 99.93898% | 4 | 0.06102% | 0 |
| L8 | 6555 | 6551 | 6551 | 99.93898% / 99.93898% | 4 | 0.06102% | 0 |
| Q32 | 6555 | 6545 | 6545 | 99.84744% / 99.84744% | 10 | 0.15256% | 0 |

All 24 failed terminals are `unknown` provider/delivery outcomes (6/4/4/10 by judge); 17 occurred on harmful-reference cells and seven on benign-reference cells. Zero format, refusal, truncation or other terminal-failure categories were observed. HTTP metadata across failures: 429×2, 503×3, absent×19. Unknown outcomes are not silently assigned benign/harmful. Raw and outer-fence-normalized rates match; Gemma 1B stayed in the roster. G1/G27/Q32 used the frozen JSON-schema mode; L8 used the frozen JSON-object fallback. Successful parsing does not prove provider-side schema enforcement.

## Support, leverage and supporting agreement

96 linked components total; harmful component counts G1=78, G27=56, L8=90, Q32=76. All support/leverage heuristics pass (≥30 overall, ≥5 harmful/source, maximum component fraction ≤20%). Distinct components do not prove independence.

| Target | Absolute coefficient sum H | Max component fraction | Conditional variance bound | 1.96 reference scale (points) |
| --- | ---: | ---: | ---: | ---: |
| Delta | 2.000000 | 1.3203% | 0.01155610 | 21.0699 |
| G1 | 2.666667 | 1.3737% | 0.02102017 | 28.4167 |
| G27 | 2.666667 | 1.3737% | 0.02102017 | 28.4167 |
| L8 | 2.666667 | 1.2680% | 0.02006274 | 27.7620 |
| Q32 | 2.666667 | 1.3191% | 0.02088226 | 28.3234 |

Variance bounds and 1.96 scales are descriptive conditional diagnostics, not confidence intervals or power guarantees.

| Judge | Valid-only binary agreement | Balanced accuracy | Harmful recall | Benign specificity | Mean absolute ordinal error |
| --- | ---: | ---: | ---: | ---: | ---: |
| G1 | 73.355% | 52.629% | 88.433% | 16.824% | 1.3969 |
| G27 | 83.972% | 70.475% | 93.810% | 47.140% | 0.9382 |
| L8 | 36.025% | 53.418% | 23.346% | 83.490% | 1.9799 |
| Q32 | 77.433% | 73.090% | 80.600% | 65.580% | 1.1204 |

Agreement is supporting and valid-only; denominators and failure rates are above. It measures agreement with interpreted released labels, not proven safety accuracy. Supporting pooled raw-row bounds are −2.2666 to −2.0895 points; equal-four-roster bounds are −12.1210 to −12.0037 points. These change weighting/estimands (equal-four loses the primary margin-cancellation property), so they cannot replace the family-balanced primary.

## Limits and disposition

This is a selected Coin Flip release, not an unselected deployment population or population attack-success estimate. Potential response truncation (~256-token historical generation), missing context, label error, linked-history dependence, content/capacity specialization, contamination and selection remain plausible explanations. Current hosted snapshots/quantization are recorded but historical generator identity is unverified; nominal-family associations do not establish self-recognition, intrinsic bias or causation. Gemma appears twice in the roster and is balanced as one family. Component bootstrap tail probabilities are approximate, not exact finite-sample guarantees.

The audit anchored embedded eligible responses and manifests to the frozen configuration; it did not independently regenerate eligibility from the original CSV during this offline stage. Local raw evidence is retained but not published. **H2 has not run**: this primary result does not satisfy the inherited H1-positive scheduling gate, and any changed direction requires Sterling’s review and separate paid-call approval.

## Reproduction and provenance

Analysis implementation commit: `66f38c7c376a4f4ddfd2910842cd8b4f3624e2b2`. Python 3.15.0; NumPy 2.5.4. Canonical configuration identity: `cc556ee3d202d91b89035151c0171eb2bda3bd3a262bcfc79ddde70b754c4147`. Analysis API: `select_study_report` via the existing offline CLI; no statistical method or code change.

```bash
uv run python -m safety_judge report \
  --configuration runs/main-7d14b00a/configuration.json \
  --journal runs/main-7d14b00a/journal.jsonl \
  --output runs/h1-29cadb5c/full-report.json --replicates 9999
```

Use a fresh output path when reproducing (the writer refuses overwrite). The full report contains private row-level identifiers/terms and stays ignored. Published JSON deliberately selects aggregate bounds, tests, counts and diagnostics only; it excludes IDs, raw completions, per-item coefficients, row weights and selected flips.

| Local evidence | SHA-256 |
| --- | --- |
| `runs/main-7d14b00a/configuration.json` | `998329c6142cfb762612c04b7d44a292b539c73bbd3f53ffae6120b0df547077` |
| `runs/main-7d14b00a/journal.jsonl` | `f506d92ba246b98bb432b579ac6b6c518d9153b5c63f7f7f8c9b32d77980d49e` |
| `runs/main-7d14b00a/final-1792268243937733000.json` | `9f4e98dbaf9418ee8535fb181ba40ef9400be22409fb5154da4bcc87c1d84a2e` |
| `runs/main-7d14b00a/main_driver.py` | `17c3c55c957d3ce6416283049d79f2372490db6ee969d9bf774e64ce0f34ad75` |
| `runs/h1-29cadb5c/full-report.json` | `cef4c71f4cb3f18681117ed42243e410417164a79fe1a660e02cc747ca67b25c` |
