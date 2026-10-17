# Research process — publication edition

## Publication-history notice

This is a retrospective publication summary prepared after the completed main study. For privacy, this same summary replaces the original operational log in every historical commit where that log existed. Its presence in an older commit does **not** mean the outcomes below were known at that time. The original private repository retains the dated record. This rewritten public history is not independent evidence of preregistration timing.

## Current state

- The completed main study assigned 6,555 eligible responses to four judges: 26,220 cells.
- The sole preregistered primary tested pooled nominal-own-family leniency exceeding five percentage points.
- Pooled finite-data completion bounds were +0.4333 to +0.5971 points; p=.9989.
- The primary claim was not supported; this is not proof of no family effect or judge safety.
- No Holm-corrected per-judge secondary claim passed.
- Supporting agreement and all requested exploratory sensitivities are published as aggregates.
- The boundary-label-error heuristic reversed the pooled sign at its 1% scenario.
- All 24 provider/delivery failures remain accounted for; zero format failures were observed.
- H2 was not run; the exploratory thinking-on arm is dropped for now.
- Public reproduction regenerates figures/tables from aggregates; raw evidence remains private.

## Research decisions and limitations

Initial inquiry compared model-evaluation and safety-judge approaches, followed by context-free red-team review. Alternatives included reference-accuracy-first studies, decomposed rubrics, own-family contrasts, and paraphrase interventions. The chosen study centered a pooled nominal-family contrast; accuracy became supporting evidence, decomposition was excluded, and a small paraphrase pilot remained exploratory and unexecuted.

All four nominal generator models judged every eligible response. Both Gemmas form one family. Released labels map to ordinal `1 + 4 × released_label`; harmful means released label ≥0.5 and judge ordinal ≥3. This is an interpretation, not verified safety ground truth. The selected dataset cannot establish population attack-success rates. Historical generator/checkpoint equivalence, annotation context, completeness, dependence, selection, contamination and possible truncation remain limitations.

The locally preregistered sole primary used the five-point boundary, one-sided alpha .025 and a 97.5% lower bound. Four secondary claims required the primary gate, Holm correction at .025 and conservative simultaneous lower bounds. Exploratory 3/5/10-point thresholds were fixed for every judge and never selected a headline. Missing outputs remained unknown binary outcomes with sharp completion bounds; 9,999 shared component-bootstrap draws supplied separate approximate inferential bounds. The label-error analysis was a fixed single-flip-ranked boundary heuristic, not a measured error rate or exact adversarial optimum.

Two pre-main measurement deviations followed smoke tests: one deterministic outer-Markdown-fence normalization rule and provider structured-output modes with an explicit unsupported-mode fallback. Raw and normalized parse rates remained separately reported. G1, G27 and Q32 used JSON schema; L8 used JSON object. The final modes were frozen before the main matrix; earlier-mode smoke outputs were diagnostic only. Qwen thinking was disabled. Every judge retained the same rubric, temperature 0, top-p 1 and 2,048-token output cap.

Independent final audit verified the saved main evidence, including journal integrity, terminal coverage and failure accounting. It did not independently regenerate eligibility from the source CSV. Analysis retained the fixed estimand and sensitivities despite the null primary. H2 was not executed. A later exploratory thinking-on smoke produced no usable model outputs; it was excluded from H1 and is not a completed extra arm.

See [Methods](methods.md), [H1 results](h1-results.md), [aggregate results](h1-aggregate-results.json), and the [README](../README.md) for exact methods, bounds, agreement, limitations and reproduction. These links describe the final publication package and may not exist in early historical trees.
