# OpenCode leCore file-repair tool-loop benchmark

One public fixture, same GLM 5.3 Flash model and prompt, maximum six provider turns and 1,200 output tokens per turn. Actual read/write tools are restricted to the fixture. The adapter runs before every provider turn. This measures a real tool loop, not the OpenCode CLI.

| Arm | Hidden grader | Requests | Actual input tokens | Actual output tokens | Cache read tokens | Estimated USD | Elapsed seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | FAIL | 2 | 15408 | 1256 | 7552 | 0.002033 | 21.29 |
| lecore | PASS | 3 | 18288 | 1072 | 0 | 0.003279 | 20.31 |

The baseline read both required files and described the correct fixes but left the source unchanged. Its answer was truncated; an output-limit explanation is an inference because this first run did not preserve the finish reason. The leCore arm wrote a source edit that passed all hidden behavioral and validation checks. Both kept valid tool histories. The successful arm used an extra turn, more input tokens overall, and no cached reads, so this does not show a whole-task cost improvement. A single task cannot establish broader coding improvements.

Costs are estimates using the published Zen rates, not observed billed charges. Raw results, exact edited source, all failed checks, provider usage and adapter metrics: [coding-zen.json](coding-zen.json).
