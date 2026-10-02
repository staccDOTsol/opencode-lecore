# OpenCode with leCore

This fork applies local leCore context processing before OpenCode sends model requests. It is enabled by default, uses the selected provider and model unchanged, and does not depend on a model calling a memory tool. OpenCode Zen works through the normal credential store.

## Run

```sh
git clone --recurse-submodules https://github.com/staccDOTsol/opencode-lecore.git
cd opencode-lecore
bun install --frozen-lockfile
script/lecore-setup.sh
script/lecore.sh auth login --provider opencode
script/lecore.sh --model opencode/glm-5.3-flash
```

Call `script/lecore.sh` by its absolute path from another directory to work on that project. It preserves the caller's current directory. The setup creates an isolated Python environment with NumPy; it does not change the system Python. The engine is pinned in [lecore.lock.json](packages/lecore/lecore.lock.json) and the `vendor/lecore` submodule.

## Context processing

The TypeScript adapter preserves system instructions, the latest user message, recent messages, reasoning, images, tool inputs, and call/result identifiers. It archives ordinary conversation text and tool-output text in a local worker. Large older text can become a short receipt plus bounded retrieved evidence. Exact originals remain in the local store. Retrieval uses leCore's BM25 implementation and exact-containment index, with source citations, incremental indexing, and explicit no-match results.

Memory is partitioned by canonical workspace path and session ID. It survives provider history compaction and worker restart. The default location is `$XDG_STATE_HOME/opencode/lecore`, or `~/.local/state/opencode/lecore`. These files contain original conversation and tool text; deleting a session partition removes its memory. Retrieved text goes in an ordinary user message and is labeled as evidence.

Both the legacy OpenCode request path and the native session runner use the adapter, including tool continuations and compaction. Auxiliary calls through the legacy path use the same adapter. Missing Python, NumPy, engine source, corrupt stores, and worker timeouts are visible errors. The fork does not silently claim memory is active after a failure.

## Configuration

```jsonc
{
  "lecore": {
    "enabled": true,
    "recentMessages": 6,
    "minimumChars": 6000,
    "budgetChars": 12000,
    "timeoutMs": 30000
  }
}
```

`LECORE_PYTHON` selects an existing Python runtime. `LECORE_SOURCE` can override the vendored engine. For an explicit baseline, set `OPENCODE_LECORE=0` or configure `lecore.enabled: false`; disabled mode returns the original request messages unchanged. Explicit configuration takes precedence over the environment flag.

Archiving and retrieval do not guarantee that every relevant fact fits in the next model request. Protected recent content can still be large. Bounded lexical retrieval can miss a paraphrased fact. Read-tool source changes are detected relative to the first leCore indexing; historical tool outputs may already be stale at that first indexing. Exact originals remain historical evidence. Paired benchmarks report these limits without treating character reduction as measured model-token savings.

The worker bounds retrieved context and caches active indexes. The exact-original archive grows with observations. This integration does not replace the model's KV cache or make total storage constant.

## Verification and benchmarks

```sh
cd packages/lecore
LECORE_PYTHON="$PWD/.venv/bin/python" bun test
.venv/bin/python -m unittest discover -s python -p 'test_*.py' -v
```

See [paired benchmark commands and methodology](packages/opencode/script/lecore/README.md). Both arms use the same Zen model, raw histories, generation settings, and strict grader. The retrieval suite and file-tool loop measure separate behaviors. They are a small integration benchmark, not a claim of general coding improvement.

The first [live Zen retrieval run](packages/opencode/script/lecore/results/zen.md) passed 18/18 cases in both arms and reduced input tokens by 18.8%; median latency increased 17.2%. The [matched coding followup](packages/opencode/script/lecore/results/coding-zen-full.md) passed both arms and reduced input tokens by 20.1%, but estimated provider cost was 3.28 times higher and latency roughly doubled, with fewer provider cache hits and more generated output. Fewer input tokens alone do not establish lower cost or faster inference. A separate actual CLI smoke test passed both arms without triggering compression; its timing differences do not measure compression benefits.

Upstream OpenCode baseline: `108b988a08227df45417f27905a4d6b27ad49b6d` (`dev`, version 1.18.34). leCore engine: `e9ffb16bb3706fb61d68148a3489e88d8fb4ec54` (0.2.27).
