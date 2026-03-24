import { describe, expect, it } from "vitest";

import {
  THINKING_PROVIDER_OPTIONS,
  formatThinkingPolicyLabel,
  getThinkingEditorStateFromPolicy,
  llmHasThinkingSelector,
} from "./llmThinking";

describe("llmThinking MiniMax fallback handling", () => {
  it("does not expose MiniMax in anthropic-compatible provider options", () => {
    expect(
      THINKING_PROVIDER_OPTIONS.anthropic_compatible.map((option) => option.value),
    ).not.toContain("minimax");
  });

  it("downgrades legacy MiniMax thinking policies to the Auto editor state", () => {
    expect(
      getThinkingEditorStateFromPolicy(
        "anthropic_compatible",
        "minimax-anthropic-thinking-enabled",
      ),
    ).toEqual({
      provider: "auto",
      detailValue: "",
      effortValue: "",
      budgetTokens: null,
    });
  });

  it("hides labels and chat toggles for unsupported legacy MiniMax policies", () => {
    expect(
      formatThinkingPolicyLabel("minimax-anthropic-thinking-enabled"),
    ).toBeNull();
    expect(
      llmHasThinkingSelector({
        thinking_policy: "minimax-anthropic-thinking-enabled",
        thinking_effort: null,
      }),
    ).toBe(false);
  });
});
