# OpenCode leCore paired benchmark

Run: 2026-10-02T22:58:11.051Z. Upstream commit: `108b988a08227df45417f27905a4d6b27ad49b6d`. Model: `glm-5.3-flash`, temperature 0, maximum 512 output tokens, retries disabled. Measured live Zen requests.

This measures the fork's real model-input adapter with raw synthetic histories. It is not a full coding-agent benchmark or official LongMemEval result. Each answer key stays outside the adapter input, seeds alter the observed values, each case/arm uses isolated memory, and order alternates between seeds. Every failed case is retained in the raw report.

| Arm | Correct / cases | Actual input tokens | Actual output tokens | Cache read tokens | Estimated USD | Total ms | Preparation ms | Invalid tool histories |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 18/18 | 127581 | 2090 | 0 | 0.020182 | 35627 | 4 | 0 |
| lecore | 18/18 | 103623 | 2624 | 64 | 0.016848 | 44663 | 1012 | 0 |

Pricing estimate for GLM 5.3 Flash: $0.15 per million uncached input tokens, $0.50 per million output tokens, $0.03 per million cached input tokens ([Zen pricing](https://opencode.ai/docs/zen/)). This is an estimate based on published rates, not an observed charge. Raw provider usage and character diagnostics are recorded separately.

Raw report: [zen.json](zen.json).

The paired retrieval tasks all passed: 18/18 baseline and 18/18 leCore. Actual input tokens fell 18.78%. Published-rate estimated cost fell 16.52%. Output tokens increased. Median recorded request latency rose from 1.865s to 2.186s. This run provides no latency improvement or broad coding-quality claim.
