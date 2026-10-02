export * as ConfigLecore from "./lecore"

import { Schema } from "effect"
import { NonNegativeInt, PositiveInt } from "../schema"

export class Info extends Schema.Class<Info>("Config.Lecore")({
  enabled: Schema.optional(Schema.Boolean).annotate({
    description: "Use the pinned local leCore engine on every inference (default: true in this fork)",
  }),
  recentMessages: Schema.optional(PositiveInt).annotate({
    description: "Number of recent messages retained verbatim (default: 6); latest user intent is always retained",
  }),
  minimumChars: Schema.optional(NonNegativeInt).annotate({
    description: "Minimum older textual bulk before archival optimization (default: 6000 characters)",
  }),
  budgetChars: Schema.optional(NonNegativeInt).annotate({
    description: "Maximum recalled evidence characters per inference (default: 12000)",
  }),
  python: Schema.optional(Schema.String).annotate({ description: "Python executable with NumPy installed" }),
  workerPath: Schema.optional(Schema.String).annotate({ description: "Override the local JSONL worker path" }),
  timeoutMs: Schema.optional(PositiveInt).annotate({ description: "Local engine deadline (default: 30000 ms)" }),
  cacheDirectory: Schema.optional(Schema.String).annotate({ description: "Local persistent leCore storage directory" }),
}) {}
