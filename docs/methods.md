# Methods

This study asks whether safety judges label harmful responses from their own nominal model family as benign more often than comparable responses from other families. It measures a **relative family association**, not self-recognition, intrinsic bias or a causal effect.

## Population and judges

The frozen Coin Flip release yielded **6,555 eligible responses** after duplicate/conflict handling, grouped into **96 linked components**. Interpreted released labels mark 5,173 as harmful and 1,382 as benign. Every response was assigned to all four judges, producing 26,220 terminal cells. The final artifact audit checked the embedded eligible population against frozen manifests; it did not independently repeat the original CSV eligibility audit.

| Role | Hosted model string | Route | Recorded precision |
| --- | --- | --- | --- |
| G1 | `google/gemma-3-1b-it:featherless-ai` | Hugging Face / Featherless | BF16 |
| G27 | `google/gemma-3-27b-it` | DeepInfra | FP8 |
| L8 | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | DeepInfra | FP8 |
| Q32 | `Qwen/Qwen3-32B` | DeepInfra | FP8 |

These are the current hosted identities recorded for the run, not verified matches to historical generator weights. Both Gemmas belong to the same nominal family.

## Measurement

All judges received the same source-derived five-level compliance rubric: refusal at 1 through full direct compliance at 5, regardless of technical correctness or feasibility. Released reference labels were mapped as `1 + 4 × released_label`; reference label ≥0.5 and judge ordinal ≥3 count as harmful. This is an approved interpretation of released labels, not independently established safety ground truth. The rubric is available in [`examples/rubric.json`](../examples/rubric.json).

Generation used temperature 0, top-p 1 and a 2,048-token output cap. Qwen thinking was disabled. G1, G27 and Q32 used JSON-schema requests; L8 used JSON-object mode after a predeclared unsupported-schema fallback. The strict parser accepts only an object with an integer ordinal from 1 to 5 and no extra fields. A fixed normalizer can remove one whole outer Markdown fence and surrounding whitespace, with no JSON repair. Raw and normalized parsing are reported separately.

The protocol was preregistered **locally**, with dated decisions in the repository, not registered externally. Outer-fence normalization and structured-output modes were documented pre-main deviations prompted by smoke tests. The main matrix used the final frozen modes; earlier-mode smoke outputs were diagnostic only.

## Primary and secondary tests

H1 uses harmful-reference responses. Within each generator, weights balance linked components, then attacks within components, then responses within attacks. Judge and source margins are G1=1/6, G27=1/6, L8=1/3 and Q32=1/3, giving each nominal family equal mass.

The pooled contrast compares weighted benign-label rates within versus outside nominal families. Each secondary contrast compares one judge's own/outside contrast with outside-family judge comparators. Positive values mean relative own-family leniency. This balancing addresses shared additive source/judge effects; it does not remove every content or capability confound.

- **Sole primary:** pooled effect Δ; null Δ≤.05, alternative Δ>.05. Rejection requires p≤.025 and a one-sided 97.5% lower bound above five percentage points.
- **Four secondaries:** the same five-point boundary for each judge. Claims require primary rejection, four-test Holm correction at .025, and conservative one-sided 99.375% lower bounds above five points.
- **Exploratory:** every judge at 3, 5 and 10 points, without selecting a headline from these comparisons.

Unknown outcomes remain binary variables. Sharp completion bounds minimize and maximize each fixed contrast over all their possible values; they describe missing-output uncertainty in the finite dataset. No midpoint is imputed. Bootstrap confidence bounds are a separate form of uncertainty.

Inference resamples all 96 components with replacement using **9,999 shared draws**, seed **2026101701**, Python Random MT19937/randrange. All judges, rows and failures stay paired; component multiplicities change source denominators. The frozen centered lower-endpoint test and nearest-rank basic bounds are implemented in the analysis code. Tail probabilities are approximate and require independent representative components from the selected-response process—assumptions not established by this dataset.

## Supporting analyses and missing outputs

Binary agreement, harmful recall, benign specificity, their mean (balanced accuracy), and ordinal absolute error use **valid outputs only** against interpreted reference labels. Coverage is reported alongside them. They assess reference agreement, not proven safety accuracy.

All 24 provider/delivery failures remain accounted for: G1 6, G27 4, L8 4 and Q32 10. Seventeen are on harmful-reference cells and seven on benign-reference cells. There were zero observed format failures, and raw/normalized parse counts matched for every judge. Parsing success does not demonstrate schema enforcement or correct judgments.

The label-error sensitivity ranks ordinal-2/3 references by their effect on the pooled lower endpoint after a single 2↔3 flip, breaking ties by source ordinal. Each scenario simultaneously flips the first distinct 66, 328 or 656 candidates (ceil of 1%, 5% or 10% of all responses), then recomputes weights, support and contrasts. This frozen heuristic is neither a measured annotation-error rate nor an exact adversarial optimum. Alternative weighting and additive-fit results are supporting analyses of different assumptions, not replacements for the primary.

## Interpretation and reproduction

The pooled completion bounds were **+0.433 to +0.597 points**, with p=.9989: the five-point primary was not supported. No secondary claim passed. The 1% label-error scenario reverses the pooled sign. Full numerical results and limits are in [H1 results](h1-results.md).

Selection, possible historical response truncation near 256 tokens, missing context, reference error, model-version mismatch, contamination and dependence limit interpretation. This study cannot establish population attack-success rates or judge safety. **H2 was not run. The exploratory thinking-on arm is dropped for now.**

The public renderer reads only [committed aggregates](h1-aggregate-results.json), producing [bounds](figures/h1-bounds.svg) and [agreement](figures/judge-agreement.svg) figures plus [H1](tables/h1-bounds.csv), [agreement](tables/judge-agreement.csv), [label-error](tables/label-error.csv), [exploratory thresholds](tables/exploratory-thresholds.csv) and [failure](tables/failures.csv) tables. It reproduces tables and figures, not the underlying bootstrap or selected label flips. Full offline analysis requires private saved configuration and journal evidence; the [results provenance](h1-results.md#reproduction-and-provenance) records its recipe and hashes. No source text, raw completions or per-item outputs are published in this package.
