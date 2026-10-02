import { afterAll, beforeAll, describe, expect } from "bun:test"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { closeWorkers, transformMessages } from "@opencode-ai/lecore"
import { LLM, LLMClient, Message } from "@opencode-ai/llm"
import { OpenAIChat } from "@opencode-ai/llm/protocols/openai-chat"
import { RequestExecutor, WebSocketExecutor } from "@opencode-ai/llm/route"
import { Effect, Layer, DateTime, Stream } from "effect"
import { FetchHttpClient } from "effect/unstable/http"
import { Config } from "@opencode-ai/core/config"
import { ConfigLecore } from "@opencode-ai/core/config/lecore"
import { ConfigCompaction } from "@opencode-ai/core/config/compaction"
import { EventV2 } from "@opencode-ai/core/event"
import { LecoreInference } from "@opencode-ai/core/session/lecore"
import { SessionCompaction } from "@opencode-ai/core/session/compaction"
import { SessionMessage } from "@opencode-ai/core/session/message"
import { SessionSchema } from "@opencode-ai/core/session/schema"
import { SessionEvent } from "@opencode-ai/core/session/event"
import { testEffect } from "./lib/effect"

const root = await mkdtemp(join(tmpdir(), "opencode-lecore-native-"))
const captured: Record<string, unknown>[] = []
const publications: string[] = []
let server: ReturnType<typeof Bun.serve>
const it = testEffect(
  Layer.mergeAll(
    LLMClient.layer.pipe(
      Layer.provide(
        Layer.mergeAll(RequestExecutor.layer.pipe(Layer.provide(FetchHttpClient.layer)), WebSocketExecutor.layer),
      ),
    ),
    Layer.mock(EventV2.Service, {
      publish: <D extends EventV2.Definition>(event: D, data: EventV2.Data<D>) =>
        Effect.sync((): EventV2.Payload<D> => {
          publications.push(event.type)
          return { id: EventV2.ID.create(), type: event.type, data }
        }),
    }),
  ),
)

beforeAll(() => {
  server = Bun.serve({
    port: 0,
    async fetch(request) {
      captured.push((await request.json()) as Record<string, unknown>)
      return new Response(
        'data: {"id":"local","choices":[{"delta":{"role":"assistant","content":"Summary done"},"finish_reason":null}]}\n\n' +
          'data: {"id":"local","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n' +
          "data: [DONE]\n\n",
        { headers: { "Content-Type": "text/event-stream" } },
      )
    },
  })
})

afterAll(async () => {
  server.stop(true)
  closeWorkers()
  await rm(root, { recursive: true, force: true })
})

describe("native core lecore inference", () => {
  for (const enabled of [false, true]) {
    it.live(`preserves native request identity and sends ${enabled ? "optimized" : "baseline"} wire text`, () =>
      Effect.gen(function* () {
        const client = yield* LLMClient.Service
        const model = OpenAIChat.route
          .with({ endpoint: { baseURL: `${server.url.origin}/v1` } })
          .model({ id: "local-model" })
        const original =
          "Unrelated telemetry. ".repeat(80) + "MIDDLE_NATIVE_SENTINEL_4917" + "Unrelated telemetry. ".repeat(80)
        const request = LLM.request({
          model,
          system: "PROTECTED_NATIVE_SYSTEM",
          tools: [],
          messages: [
            Message.user("Inspect configuration."),
            Message.assistant(original),
            ...Array.from({ length: 8 }, () => Message.assistant("Unrelated satellite output. ".repeat(40))),
            Message.user("What is the cobalt gateway?"),
          ],
        })
        const optimized = yield* LecoreInference.prepare({
          request,
          workspace: root,
          sessionID: crypto.randomUUID(),
          purpose: "agent-turn",
          config: { enabled, cacheDirectory: root, minimumChars: 0, recentMessages: 2, budgetChars: 1000 },
        })
        if (!enabled) expect(optimized).toBe(request)
        expect(optimized.model).toBe(request.model)
        expect(optimized.system).toEqual(request.system)
        yield* client.stream(optimized).pipe(Stream.runDrain)
        const wire = JSON.stringify(captured.at(-1))
        expect(wire).toContain("PROTECTED_NATIVE_SYSTEM")
        expect(wire).toContain("What is the cobalt gateway?")
        expect(wire.includes("lecore archived")).toBe(enabled)
        expect(wire.includes("MIDDLE_NATIVE_SENTINEL_4917")).toBe(!enabled)
      }),
    )

    it.live(
      `compaction uses ${enabled ? "persistent archived evidence" : "unmodified baseline"} at the real HTTP boundary`,
      () =>
        Effect.gen(function* () {
          const client = yield* LLMClient.Service
          const events = yield* EventV2.Service
          const sessionID = SessionSchema.ID.make(`ses_${crypto.randomUUID()}`)
          const lecore = { enabled, cacheDirectory: root, minimumChars: 0, budgetChars: 2000 }
          if (enabled)
            yield* Effect.promise(() =>
              transformMessages(
                [
                  {
                    role: "user",
                    content: "Earlier observation: project cobalt signing header is x-cobalt-retained-3349.",
                  },
                ],
                { workspace: root, sessionID, config: lecore },
              ),
            )
          const model = OpenAIChat.route
            .with({ endpoint: { baseURL: `${server.url.origin}/v1` }, limits: { context: 100_000, output: 128 } })
            .model({ id: "local-summary" })
          const request = LLM.request({ model, messages: [Message.user("Summarize task state.")] })
          const compact = SessionCompaction.make({
            events,
            llm: client,
            workspace: root,
            config: [
              new Config.Document({
                type: "document",
                info: new Config.Info({
                  lecore: new ConfigLecore.Info(lecore),
                  compaction: new ConfigCompaction.Info({ keep: new ConfigCompaction.Keep({ tokens: 0 }) }),
                }),
              }),
            ],
          })
          const message = SessionMessage.User.make({
            id: SessionMessage.ID.create(),
            type: "user",
            time: { created: DateTime.makeUnsafe(0) },
            text: "Report project cobalt's signing header after previous context was lost.",
          })
          const result = yield* compact.compactAfterOverflow({
            sessionID,
            model,
            request,
            entries: [{ seq: 1, message }],
          })
          expect(result).toBe(true)
          const wire = JSON.stringify(captured.at(-1))
          expect(wire).toContain("## Objective")
          expect(wire).toContain("Report project cobalt")
          expect(wire.includes("x-cobalt-retained-3349")).toBe(enabled)
          expect(publications.slice(-2)).toEqual([
            SessionEvent.Compaction.Started.type,
            SessionEvent.Compaction.Ended.type,
          ])
        }),
    )
  }
})
