# OpenCode leCore matched file-repair followup

This uses the same public retry fixture, GLM 5.3 Flash, prompt and temperature 0 as the initial tool-loop run. To resolve its truncated baseline answer, the matched followup increases the output cap from 1,200 to 4,096 tokens and limits each arm to three provider turns. Each arm uses fresh fixture files and fresh memory. The original failed result is retained in [coding-zen.json](coding-zen.json). Both followup arms finished with tool-calls, tool-calls, stop and passed every hidden behavioral and validation check.

| Arm | Hidden grader | Requests | Actual input tokens | Actual output tokens | Cache read tokens | Estimated USD | Elapsed seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | PASS | 3 | 23729 | 744 | 23296 | 0.001136 | 13.84 |
| lecore | PASS | 3 | 18970 | 1755 | 0 | 0.003723 | 27.70 |

Input tokens fell 20.06%, but estimated whole-task cost rose 3.28× and elapsed time rose 2.00×. The baseline had many cached reads; leCore had none and generated more output. This result does not establish lower cost, faster completion, or higher coding quality. Provider cache warmth also differs between cohorts; do not attribute every observed difference solely to memory.

Costs use published Zen rates and are estimates rather than observed billed charges. This cohort preserves startup implementation hashes. A later provenance identity fix is covered separately by unit tests; these fixtures use unique sources and do not exercise that bug. Raw results, final edited source, per-turn usage and finish reasons, and adapter metrics: [coding-zen-full.json](coding-zen-full.json).
