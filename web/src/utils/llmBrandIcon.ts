/**
 * Declarative brand icon matchers keyed by provider/model fragments.
 * Why: users can rename LLM configurations, but the model identifier usually
 * remains the most stable signal for choosing a provider icon.
 */
const LLM_BRAND_ICON_MATCHERS: Array<{ keywords: string[]; iconPath: string }> = [
  { keywords: ["claude"], iconPath: "/llms/claude.svg" },
  { keywords: ["deepseek"], iconPath: "/llms/deepseek.svg" },
  { keywords: ["doubao"], iconPath: "/llms/doubao.svg" },
  { keywords: ["gemini"], iconPath: "/llms/gemini.svg" },
  { keywords: ["gpt"], iconPath: "/llms/gpt.svg" },
  { keywords: ["glm"], iconPath: "/llms/glm.svg" },
  { keywords: ["hunyuan"], iconPath: "/llms/hunyuan.svg" },
  { keywords: ["kimi"], iconPath: "/llms/kimi.svg" },
  { keywords: ["minimax"], iconPath: "/llms/minimax.svg" },
  { keywords: ["qwen"], iconPath: "/llms/qwen.svg" },
];

/**
 * Resolve one brand icon from a model identifier.
 *
 * @param model The provider model identifier configured on the LLM.
 * @returns The public asset path for the matched brand icon, or null when the
 *   model does not map to a known provider brand.
 */
export function getLLMBrandIconPath(model: string | null | undefined): string | null {
  const normalizedModel = model?.toLowerCase().trim();
  if (!normalizedModel) {
    return null;
  }

  const match = LLM_BRAND_ICON_MATCHERS.find(({ keywords }) =>
    keywords.some((keyword) => normalizedModel.includes(keyword)),
  );

  return match?.iconPath ?? null;
}
