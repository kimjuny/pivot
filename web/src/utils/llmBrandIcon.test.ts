import { describe, expect, it } from "vitest";

import {
  getLLMBrandIconCandidates,
  getLLMBrandIconPath,
} from "./llmBrandIcon";

describe("llm brand icon helpers", () => {
  it("matches icon file names against model identifiers", () => {
    expect(getLLMBrandIconPath("mimo-v2-pro")).toBe("/llms/mimo.svg");
    expect(getLLMBrandIconCandidates("step-2-16k")).toEqual([
      "/llms/step.svg",
    ]);
    expect(getLLMBrandIconPath("deepseek-r1")).toBe("/llms/deepseek.svg");
    expect(getLLMBrandIconPath("qwen3.5-plus")).toBe("/llms/qwen.svg");
    expect(getLLMBrandIconPath("gemini2.5-pro")).toBe("/llms/gemini.svg");
  });

  it("falls back to alias-based brands for provider namespaces", () => {
    expect(getLLMBrandIconCandidates("openai/gpt-4.1")).toEqual([
      "/llms/gpt.svg",
    ]);
    expect(getLLMBrandIconCandidates("anthropic/sonnet-4")).toEqual([
      "/llms/claude.svg",
    ]);
  });

  it("returns no candidates when the model is empty", () => {
    expect(getLLMBrandIconCandidates("")).toEqual([]);
    expect(getLLMBrandIconPath(undefined)).toBeNull();
  });
});
