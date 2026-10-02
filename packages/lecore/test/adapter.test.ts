import { afterAll, expect, test } from "bun:test"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { closeWorkers, fetchOriginal, transformMessages } from "../src/index"

const root = await mkdtemp(join(tmpdir(), "opencode-lecore-adapter-"))
const config = { cacheDirectory: root, minimumChars: 0, budgetChars: 4000, recentMessages: 2 }
const context = (sessionID: string = crypto.randomUUID()) => ({ workspace: root, sessionID, config })
const filler = () =>
  Array.from({ length: 10 }, (_, index) => ({
    role: "assistant",
    content: `Satellite-${index} operations unrelated to cobalt gateway. `.repeat(35),
  }))

afterAll(async () => {
  closeWorkers()
  await rm(root, { recursive: true, force: true })
})

test("baseline preserves array identity and every byte without starting Python", async () => {
  const messages = [{ role: "user", content: "Exact intent" }, ...filler()]
  const result = await transformMessages(messages, {
    ...context(),
    config: { enabled: false, python: "/does/not/exist" },
  })
  expect(result.messages).toBe(messages)
  expect(result.metrics.enabled).toBe(false)
  expect(result.metrics.indexedItems).toBe(0)
  expect(result.metrics.removedChars).toBe(0)
})

test("real engine compresses older text while keeping instructions and tool protocol intact", async () => {
  const call = { type: "tool-call", toolCallId: "call-1", toolName: "read", input: { filePath: "cobalt.txt" } }
  const reasoning = {
    type: "reasoning",
    text: "Protected reasoning",
    providerMetadata: { openai: { encrypted: "abc" } },
  }
  const image = { type: "image", image: new Uint8Array([1, 2, 3]), mediaType: "image/png" }
  const value =
    "Observed project cobalt gateway is gw-cobalt-42.internal.\n" + "Unrelated satellite telemetry.\n".repeat(150)
  const messages = [
    { role: "system", content: "Protected system instructions" },
    { role: "user", content: "Inspect deployment configuration and retain the objective." },
    { role: "assistant", content: [call, reasoning] },
    {
      role: "tool",
      content: [{ type: "tool-result", toolCallId: "call-1", toolName: "read", output: { type: "text", value } }],
    },
    ...filler(),
    { role: "user", content: [{ type: "text", text: "What is the project cobalt gateway?" }, image] },
  ]
  const original = JSON.stringify(messages)
  const result = await transformMessages(messages, context())
  expect(result.metrics.engine).toBe("leCore")
  expect(result.metrics.removedChars).toBeGreaterThan(0)
  expect(result.messages[0]).toBe(messages[0])
  expect(result.messages[1]).toBe(messages[1])
  expect(result.messages[2]).toBe(messages[2])
  expect(result.messages.at(-1)).toBe(messages.at(-1))
  expect(JSON.stringify(result.messages)).toContain("gw-cobalt-42.internal")
  const output = result.messages[3] as (typeof messages)[3]
  expect(output.role).toBe("tool")
  expect(output.content).toMatchObject([
    { type: "tool-result", toolCallId: "call-1", toolName: "read", output: { type: "text" } },
  ])
  expect(JSON.stringify(messages)).toBe(original)
  expect(result.messages.filter((message) => message.role === "system")).toHaveLength(1)
})

test("archived evidence survives compaction and a worker restart with exact source retrieval", async () => {
  const ctx = context()
  const value =
    "Project zephyr uses signing header x-zephyr-exact-9927.\n" + "Unrelated document material.\n".repeat(90)
  const initial = await transformMessages(
    [
      { role: "user", content: "Analyze deployment records." },
      { role: "assistant", content: value },
      ...filler(),
      { role: "user", content: "Continue analyzing records." },
    ],
    ctx,
  )
  const serialized = JSON.stringify(initial.messages)
  const item = serialized.match(/(?:item=|id=)([a-f0-9]{64})/)?.[1]
  expect(item).toBeDefined()
  const original = await fetchOriginal({ ...ctx, id: item! })
  expect(original.original).toMatchObject({ text: value })
  closeWorkers()
  const result = await transformMessages(
    [
      { role: "assistant", content: "Lossy summary: deployment records were inspected." },
      { role: "user", content: "What signing header did project zephyr use?" },
    ],
    ctx,
  )
  expect(JSON.stringify(result.messages)).toContain("x-zephyr-exact-9927")
  expect(result.metrics.recalledItems).toBeGreaterThan(0)
  expect(result.messages.at(-1)).toEqual({ role: "user", content: "What signing header did project zephyr use?" })
})

test("sessions are isolated and no-match recalls do not fabricate context", async () => {
  await transformMessages(
    [{ role: "user", content: "The private quasar secret is violet-8821." }],
    context("private-session"),
  )
  const result = await transformMessages(
    [{ role: "user", content: "What is private quasar secret?" }],
    context("different-session"),
  )
  expect(JSON.stringify(result.messages)).not.toContain("violet-8821")
  expect(result.metrics.recalledItems).toBe(0)
})

test("read-tool file changes invalidate prior evidence", async () => {
  const file = join(root, "tracked.txt")
  const value = "Project willow signing header is x-willow-obsolete.\n" + "Old deployment metadata.\n".repeat(80)
  await writeFile(file, value)
  const ctx = context()
  await transformMessages(
    [
      { role: "user", content: "Inspect deployment configuration." },
      {
        role: "assistant",
        content: [{ type: "tool-call", toolCallId: "tracked", toolName: "read", input: { filePath: file } }],
      },
      {
        role: "tool",
        content: [{ type: "tool-result", toolCallId: "tracked", toolName: "read", output: { type: "text", value } }],
      },
      ...filler(),
      { role: "user", content: "Continue" },
    ],
    ctx,
  )
  await writeFile(file, "Project willow now uses x-willow-current.\n")
  const result = await transformMessages([{ role: "user", content: "What is project willow signing header?" }], ctx)
  expect(JSON.stringify(result.messages)).not.toContain("x-willow-obsolete")
  expect(result.metrics.worker?.stale_items).toBe(1)
})

test("identical read outputs keep separate ownership when one source goes stale", async () => {
  const a = join(root, "same-a.txt")
  const b = join(root, "same-b.txt")
  const value =
    "Project aurora signing header is x-aurora-distinct-7741.\n" + "Identical deployment notes.\n".repeat(80)
  await Promise.all([writeFile(a, value), writeFile(b, value)])
  const ctx = context()
  const initial = await transformMessages(
    [
      { role: "user", content: "Inspect deployment records." },
      {
        role: "assistant",
        content: [{ type: "tool-call", toolCallId: "read-a", toolName: "read", input: { filePath: a } }],
      },
      {
        role: "tool",
        content: [{ type: "tool-result", toolCallId: "read-a", toolName: "read", output: { type: "text", value } }],
      },
      {
        role: "assistant",
        content: [{ type: "tool-call", toolCallId: "read-b", toolName: "read", input: { filePath: b } }],
      },
      {
        role: "tool",
        content: [{ type: "tool-result", toolCallId: "read-b", toolName: "read", output: { type: "text", value } }],
      },
      ...filler(),
      { role: "user", content: "Continue" },
    ],
    ctx,
  )
  expect(initial.metrics.worker?.archived_items).toBe(14)
  await rm(a)
  const recalled = await transformMessages(
    [{ role: "user", content: "What signing header does project aurora use?" }],
    ctx,
  )
  const text = JSON.stringify(recalled.messages)
  expect(text).toContain("x-aurora-distinct-7741")
  expect(text).toContain("read-b")
  expect(text).toContain("same-b.txt")
  expect(text).not.toContain("same-a.txt")
  expect(recalled.metrics.worker?.stale_items).toBe(1)
})

test("missing worker fails visibly and an already-aborted request does not wait", async () => {
  await expect(
    transformMessages([{ role: "user", content: "Hi" }], {
      ...context(),
      config: { python: "/does/not/exist", timeoutMs: 1000 },
    }),
  ).rejects.toThrow("worker could not start")
  const controller = new AbortController()
  controller.abort(new Error("canceled by user"))
  await expect(
    transformMessages([{ role: "user", content: "Hi" }], {
      ...context(),
      signal: controller.signal,
    }),
  ).rejects.toThrow("canceled by user")
})
