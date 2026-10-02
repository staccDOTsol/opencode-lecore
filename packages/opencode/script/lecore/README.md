# leCore paired benchmarks

Run from `packages/opencode` after installing workspace dependencies. Set `LECORE_PYTHON` to the Python runtime with NumPy used by the adapter. The worker source and engine location use the adapter's normal configuration.

```sh
bun run script/lecore/bench.ts --seeds 1 --cases earlier-fact,tool-continuation --out script/lecore/results/dry.json
bun run script/lecore/coding.ts --out script/lecore/results/coding-dry.json
```

Dry runs exercise the real adapter and validate transformed tool histories. They make zero model requests; their character counts do not measure model token savings or answer quality.

```sh
bun run script/lecore/bench.ts --live --seeds 3 --model glm-5.3-flash --out script/lecore/results/zen.json
bun run script/lecore/coding.ts --live --model glm-5.3-flash --max-turns 6 --out script/lecore/results/coding-zen.json
```

The live retrieval run plans 36 requests, refuses runs above `--max-requests` (40 by default), validates the chosen model against Zen's authenticated catalog, disables generation retries, caps each answer at 512 output tokens, and reads Zen credentials inside the process from `OPENCODE_API_KEY` or OpenCode's existing auth store. It never logs credentials or private project files. The file-repair run permits six provider turns per arm (12 total), maximum 1,200 output tokens per turn, and file tools confined to two generated public fixture files.

Both arms use the same model, prompts, raw observations, generation settings, and scorer. The sole controlled variable is `transformMessages(..., { config: { enabled } })`; baseline asserts the original array identity. The leCore arm uses a fresh workspace/session for every case, so it cannot reuse another answer key or benefit from an earlier arm. Arm order alternates by seed. Three seeds change the held-out values while retaining the task shape. This small suite cannot establish broad coding improvements or statistical significance.

The six raw-history tasks measure exact earlier-fact recall, applying a later correction, combining both sources, abstaining on an unstated field, ignoring an instruction embedded in an untrusted document, and continuing with complete historical tool pairs. Known fact values are present only in the observed source content; the expected answer object is given solely to the scorer. Strict grading rejects extra keys, partial answers, and unsupported values. Tool calls retain IDs and are checked for unmatched, duplicate, and reversed call/result pairs.

The coding fixture repairs exponential retry timing using actual read and write tools over a temporary directory. The adapter runs before every provider step. A separate inaccessible grader checks outputs, validation, actual source edits, and the required source/contract reads. Each arm starts from identical buggy source; neither can read the grader through its file tools.

Raw JSON reports retain every success and failure, model output, actual provider token/cache usage, latency, adapter metrics, and original/transformed character counts and hashes. The retrieval run also produces a Markdown table. Character diagnostics and published pricing estimates are separate from observed provider usage and are never represented as billed savings. These are model-input and tool-loop benchmarks, not a full OpenCode CLI benchmark or official LongMemEval/SWE-bench result.
