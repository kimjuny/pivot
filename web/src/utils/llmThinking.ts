import type { LLM } from "@/types";

/**
 * User-facing runtime mode exposed by the chat composer.
 */
export type ChatThinkingMode = "auto" | "fast" | "thinking";

/**
 * Top-level provider families shown in the LLM Thinking section.
 */
export type ThinkingProvider =
  | "auto"
  | "qwen"
  | "doubao"
  | "completion_toggle"
  | "mimo"
  | "chatgpt"
  | "claude";

/**
 * One provider option shown in the top-level Thinking selector.
 */
export interface ThinkingProviderOption {
  /** Stable provider key used by the editor. */
  value: ThinkingProvider;
  /** Human-readable label shown to the user. */
  label: string;
}

/**
 * Derived editor state for one stored thinking policy.
 */
export interface ThinkingEditorState {
  /** Selected provider family. */
  provider: ThinkingProvider;
  /** Secondary value for boolean/type/mode selectors. */
  detailValue: string;
  /** Optional effort tier used by some policies. */
  effortValue: string;
  /** Optional thinking budget for extended thinking. */
  budgetTokens: number | null;
}

const DISABLED_THINKING_POLICIES = new Set([
  "qwen-disable-thinking",
  "generic-completion-thinking-disabled",
  "doubao-completion-thinking-disabled",
  "glm-completion-thinking-disabled",
  "mimo-completion-thinking-disabled",
  "kimi-completion-thinking-disabled",
  "doubao-response-thinking-disabled",
  "mimo-anthropic-thinking-disabled",
]);

const SUPPORTED_THINKING_POLICIES = new Set([
  "auto",
  "qwen-enable-thinking",
  "qwen-disable-thinking",
  "generic-completion-thinking-enabled",
  "generic-completion-thinking-disabled",
  "doubao-completion-thinking-enabled",
  "doubao-completion-thinking-disabled",
  "glm-completion-thinking-enabled",
  "glm-completion-thinking-disabled",
  "mimo-completion-thinking-enabled",
  "mimo-completion-thinking-disabled",
  "kimi-completion-thinking-enabled",
  "kimi-completion-thinking-disabled",
  "doubao-response-thinking-enabled",
  "doubao-response-thinking-disabled",
  "openai-response-reasoning-effort",
  "claude-thinking-enabled",
  "claude-thinking-adaptive",
  "mimo-anthropic-thinking-enabled",
  "mimo-anthropic-thinking-disabled",
]);

/**
 * Top-level Thinking providers grouped by transport protocol.
 */
export const THINKING_PROVIDER_OPTIONS: Record<
  string,
  ThinkingProviderOption[]
> = {
  openai_completion_llm: [
    { value: "auto", label: "Auto" },
    { value: "qwen", label: "Qwen" },
    {
      value: "completion_toggle",
      label: "Doubao / GLM / MiMo / Kimi / DeepSeek",
    },
  ],
  openai_response_llm: [
    { value: "auto", label: "Auto" },
    { value: "doubao", label: "Doubao" },
    { value: "chatgpt", label: "ChatGPT" },
  ],
  anthropic_compatible: [
    { value: "auto", label: "Auto" },
    { value: "claude", label: "Claude" },
    { value: "mimo", label: "MiMo" },
  ],
};

/**
 * Return the default stored editor state for one provider selection.
 */
export function getDefaultThinkingEditorState(
  protocol: string,
  provider: ThinkingProvider,
): ThinkingEditorState {
  if (provider === "auto") {
    return {
      provider: "auto",
      detailValue: "",
      effortValue: "",
      budgetTokens: null,
    };
  }

  if (protocol === "openai_completion_llm") {
    if (provider === "qwen") {
      return {
        provider,
        detailValue: "true",
        effortValue: "",
        budgetTokens: null,
      };
    }
    return {
      provider,
      detailValue: "enabled",
      effortValue: "",
      budgetTokens: null,
    };
  }

  if (protocol === "openai_response_llm") {
    if (provider === "chatgpt") {
      return {
        provider,
        detailValue: "",
        effortValue: "medium",
        budgetTokens: null,
      };
    }
    return {
      provider,
      detailValue: "enabled",
      effortValue: "",
      budgetTokens: null,
    };
  }

  if (protocol === "anthropic_compatible") {
    if (provider === "claude") {
      return {
        provider,
        detailValue: "enabled",
        effortValue: "high",
        budgetTokens: 10000,
      };
    }
    return {
      provider,
      detailValue: "enabled",
      effortValue: "",
      budgetTokens: null,
    };
  }

  return {
    provider: "auto",
    detailValue: "",
    effortValue: "",
    budgetTokens: null,
  };
}

/**
 * Parse stored API values into the dynamic editor model.
 */
export function getThinkingEditorStateFromPolicy(
  protocol: string,
  policy: string,
  effort?: string | null,
  budgetTokens?: number | null,
): ThinkingEditorState {
  if (policy === "auto") {
    return getDefaultThinkingEditorState(protocol, "auto");
  }

  switch (policy) {
    case "qwen-enable-thinking":
      return {
        provider: "qwen",
        detailValue: "true",
        effortValue: "",
        budgetTokens: null,
      };
    case "qwen-disable-thinking":
      return {
        provider: "qwen",
        detailValue: "false",
        effortValue: "",
        budgetTokens: null,
      };
    case "generic-completion-thinking-enabled":
    case "doubao-completion-thinking-enabled":
    case "glm-completion-thinking-enabled":
    case "mimo-completion-thinking-enabled":
    case "kimi-completion-thinking-enabled":
      return {
        provider: "completion_toggle",
        detailValue: "enabled",
        effortValue: "",
        budgetTokens: null,
      };
    case "doubao-response-thinking-enabled":
      return {
        provider: "doubao",
        detailValue: "enabled",
        effortValue: "",
        budgetTokens: null,
      };
    case "generic-completion-thinking-disabled":
    case "doubao-completion-thinking-disabled":
    case "glm-completion-thinking-disabled":
    case "mimo-completion-thinking-disabled":
    case "kimi-completion-thinking-disabled":
      return {
        provider: "completion_toggle",
        detailValue: "disabled",
        effortValue: "",
        budgetTokens: null,
      };
    case "doubao-response-thinking-disabled":
      return {
        provider: "doubao",
        detailValue: "disabled",
        effortValue: "",
        budgetTokens: null,
      };
    case "mimo-anthropic-thinking-enabled":
      return {
        provider: "mimo",
        detailValue: "enabled",
        effortValue: "",
        budgetTokens: null,
      };
    case "mimo-anthropic-thinking-disabled":
      return {
        provider: "mimo",
        detailValue: "disabled",
        effortValue: "",
        budgetTokens: null,
      };
    case "openai-response-reasoning-effort":
      return {
        provider: "chatgpt",
        detailValue: "",
        effortValue: effort ?? "medium",
        budgetTokens: null,
      };
    case "claude-thinking-enabled":
      return {
        provider: "claude",
        detailValue: "enabled",
        effortValue: "",
        budgetTokens: budgetTokens ?? 10000,
      };
    case "claude-thinking-adaptive":
      return {
        provider: "claude",
        detailValue: "adaptive",
        effortValue: effort ?? "high",
        budgetTokens: null,
      };
    default:
      return getDefaultThinkingEditorState(protocol, "auto");
  }
}

/**
 * Convert the dynamic editor model back into stored API values.
 */
export function buildThinkingPolicyFromEditorState(
  protocol: string,
  provider: ThinkingProvider,
  detailValue: string,
  effortValue: string,
  budgetTokens: number | null,
): {
  thinking_policy: string;
  thinking_effort: string;
  thinking_budget_tokens: number | null;
} {
  if (provider === "auto") {
    return {
      thinking_policy: "auto",
      thinking_effort: "",
      thinking_budget_tokens: null,
    };
  }

  if (protocol === "openai_completion_llm") {
    let thinkingPolicy = "auto";
    if (provider === "qwen") {
      thinkingPolicy =
        detailValue === "false" ? "qwen-disable-thinking" : "qwen-enable-thinking";
    } else if (provider === "completion_toggle") {
      thinkingPolicy =
        detailValue === "disabled"
          ? "generic-completion-thinking-disabled"
          : "generic-completion-thinking-enabled";
    }
    return {
      thinking_policy: thinkingPolicy,
      thinking_effort: "",
      thinking_budget_tokens: null,
    };
  }

  if (protocol === "openai_response_llm") {
    if (provider === "chatgpt") {
      return {
        thinking_policy: "openai-response-reasoning-effort",
        thinking_effort: effortValue || "medium",
        thinking_budget_tokens: null,
      };
    }

    if (provider === "doubao") {
      return {
        thinking_policy:
          detailValue === "disabled"
            ? "doubao-response-thinking-disabled"
            : "doubao-response-thinking-enabled",
        thinking_effort: "",
        thinking_budget_tokens: null,
      };
    }
  }

  if (protocol === "anthropic_compatible") {
    if (provider === "claude") {
      if (detailValue === "adaptive") {
        return {
          thinking_policy: "claude-thinking-adaptive",
          thinking_effort: effortValue || "high",
          thinking_budget_tokens: null,
        };
      }
      return {
        thinking_policy: "claude-thinking-enabled",
        thinking_effort: "",
        thinking_budget_tokens: budgetTokens ?? 10000,
      };
    }

    if (provider === "mimo") {
      return {
        thinking_policy:
          detailValue === "disabled"
            ? "mimo-anthropic-thinking-disabled"
            : "mimo-anthropic-thinking-enabled",
        thinking_effort: "",
        thinking_budget_tokens: null,
      };
    }
  }

  return {
    thinking_policy: "auto",
    thinking_effort: "",
    thinking_budget_tokens: null,
  };
}

/**
 * Whether a provider choice should reveal a secondary selector.
 */
export function providerNeedsThinkingDetail(
  provider: ThinkingProvider,
): boolean {
  return provider !== "auto";
}

/**
 * Return a compact badge label for LLM list rows.
 */
export function formatThinkingPolicyLabel(
  policy: string,
  effort?: string | null,
): string | null {
  if (!SUPPORTED_THINKING_POLICIES.has(policy)) {
    return null;
  }
  if (policy === "auto") {
    return null;
  }
  if (!policySupportsThinkingMode(policy, effort)) {
    return "Fast Only";
  }
  return "Thinking";
}

/**
 * Whether the stored policy can expose a Thinking option in chat.
 */
export function policySupportsThinkingMode(
  policy: string,
  effort?: string | null,
): boolean {
  if (!SUPPORTED_THINKING_POLICIES.has(policy)) {
    return false;
  }
  if (policy === "auto") {
    return false;
  }
  if (DISABLED_THINKING_POLICIES.has(policy)) {
    return false;
  }
  return !(
    policy === "openai-response-reasoning-effort" &&
    (effort ?? "").trim().toLowerCase() === "none"
  );
}

/**
 * Whether the chat composer should render a Thinking selector at all.
 */
export function llmHasThinkingSelector(
  llm?: Pick<LLM, "thinking_policy" | "thinking_effort"> | null,
): boolean {
  return Boolean(
    llm &&
      SUPPORTED_THINKING_POLICIES.has(llm.thinking_policy ?? "auto") &&
      (llm.thinking_policy ?? "auto") !== "auto",
  );
}

/**
 * Return the allowed runtime modes for one LLM configuration.
 */
export function getChatThinkingModes(
  llm?: Pick<LLM, "thinking_policy" | "thinking_effort"> | null,
): ChatThinkingMode[] {
  if (!llmHasThinkingSelector(llm)) {
    return [];
  }
  if (
    policySupportsThinkingMode(
      llm?.thinking_policy ?? "auto",
      llm?.thinking_effort ?? null,
    )
  ) {
    return ["auto", "fast", "thinking"];
  }
  return ["fast"];
}

/**
 * Return the default runtime mode for one LLM configuration.
 */
export function getDefaultChatThinkingMode(
  llm?: Pick<LLM, "thinking_policy" | "thinking_effort"> | null,
): ChatThinkingMode {
  if (
    policySupportsThinkingMode(
      llm?.thinking_policy ?? "auto",
      llm?.thinking_effort ?? null,
    )
  ) {
    return "auto";
  }
  return "fast";
}
