import { describe, expect, it } from "vitest";

import {
  THINKING_PROVIDER_OPTIONS,
  formatThinkingPolicyLabel,
  getChatThinkingModes,
  getDefaultChatThinkingMode,
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

  it("defaults chat runtime mode to Auto when a thinking tier is available", () => {
    const llm = {
      thinking_policy: "openai-response-reasoning-effort",
      thinking_effort: "high",
    };

    expect(getChatThinkingModes(llm)).toEqual(["auto", "fast", "thinking"]);
    expect(getDefaultChatThinkingMode(llm)).toBe("auto");
  });
});
