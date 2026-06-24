/**
 * User-facing runtime thinking toggle exposed by the chat composer.
 *
 * Thinking is now a per-task binary choice — every LLM can be run with or
 * without provider reasoning. There is no longer a per-LLM "thinking policy"
 * configuration surface; effort tiers will be added later as a separate
 * per-LLM parameter.
 */
export type ChatThinkingMode = "enabled" | "disabled";
