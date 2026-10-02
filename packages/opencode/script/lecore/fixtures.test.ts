import { describe, expect, test } from "bun:test"
import type { ModelMessage } from "ai"
import { fixtures, score, toolIntegrity } from "./fixtures"

describe("paired benchmark instrument", () => {
  test("changes held-out values by seed while reproducing each exact history", () => {
    expect(fixtures(0)).toEqual(fixtures(0))
    expect(fixtures(0)[0].expected).not.toEqual(fixtures(1)[0].expected)
    for (const fixture of fixtures(0)) {
      const latest = String(fixture.messages.at(-1)?.content)
      for (const value of Object.values(fixture.expected)) {
        if (value !== null) expect(latest.includes(value)).toBeFalse()
      }
    }
  })

  test("requires both evidence halves, rejects extra fields and invalid JSON", () => {
    const expected = { gateway_hostname: "gw-abc.internal", vault_handle: "vault/def" }
    expect(score('{"gateway_hostname":"gw-abc.internal"}', expected)).toBeFalse()
    expect(
      score('{"gateway_hostname":"gw-abc.internal","vault_handle":"vault/def","invented":"x"}', expected),
    ).toBeFalse()
    expect(score("The answer is gw-abc.internal", expected)).toBeFalse()
    expect(score(JSON.stringify(expected), expected)).toBeTrue()
    expect(score("```json\n" + JSON.stringify(expected) + "\n```", expected)).toBeTrue()
    expect(score('{"failover_approval_code":"unknown"}', { failover_approval_code: null })).toBeFalse()
    expect(score('{"failover_approval_code":null}', { failover_approval_code: null })).toBeTrue()
  })

  test("detects protocol corruption instead of treating it as memory improvement", () => {
    const intact = fixtures(0).find((fixture) => fixture.id === "tool-continuation")!
    expect(toolIntegrity(intact.messages)).toEqual([])
    const call: ModelMessage = {
      role: "assistant",
      content: [{ type: "tool-call", toolCallId: "c", toolName: "read", input: {} }],
    }
    const result: ModelMessage = {
      role: "tool",
      content: [{ type: "tool-result", toolCallId: "c", toolName: "read", output: { type: "text", value: "done" } }],
    }
    expect(toolIntegrity([result, call])).toContain("orphan-result:c")
    expect(toolIntegrity([call])).toContain("missing-result:c")
    expect(toolIntegrity([call, result, result])).toContain("duplicate-result:c")
  })
})
