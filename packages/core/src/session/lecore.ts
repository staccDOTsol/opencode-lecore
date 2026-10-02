export * as LecoreInference from "./lecore"

import { isEnabled, transformMessages, type LecoreConfig } from "@opencode-ai/lecore"
import { LLM, type LLMRequest } from "@opencode-ai/llm"
import { Effect } from "effect"

export const prepare = Effect.fn("LecoreInference.prepare")(function* (input: {
  request: LLMRequest
  workspace: string
  sessionID: string
  purpose: string
  config?: LecoreConfig
}) {
  if (!isEnabled(input.config)) return input.request
  const optimized = yield* Effect.promise((signal) =>
    transformMessages(input.request.messages, {
      workspace: input.workspace,
      sessionID: input.sessionID,
      purpose: input.purpose,
      config: input.config,
      signal,
    }),
  )
  yield* Effect.logInfo("lecore inference", optimized.metrics)
  return optimized.messages === input.request.messages
    ? input.request
    : LLM.updateRequest(input.request, { messages: optimized.messages })
})
