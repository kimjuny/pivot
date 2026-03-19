import { LLM_ICON_KEYS } from "../generated/llmIconManifest";

/**
 * Provider aliases that map common namespace tokens back to the icon file names
 * we store under `public/llms`.
 * Why: many model ids include a vendor namespace such as `openai/` or
 * `stepfun/`, while the design system wants the end-user-facing brand mark.
 */
const LLM_BRAND_ALIASES: Record<string, string> = {
  alibaba: "qwen",
  aliyun: "qwen",
  anthropic: "claude",
  ark: "doubao",
  bytedance: "doubao",
  chatgpt: "gpt",
  dashscope: "qwen",
  google: "gemini",
  moonshot: "kimi",
  openai: "gpt",
  stepfun: "step",
  tencent: "hunyuan",
  volcengine: "doubao",
  zhipu: "glm",
  zhipuai: "glm",
};

/**
 * Extract meaningful brand-like tokens from one model identifier.
 *
 * @param model The provider model identifier configured on the LLM.
 * @returns Lowercase tokens that can be used to guess asset file names.
 */
function getModelBrandTokens(model: string): string[] {
  return (model.toLowerCase().match(/[a-z][a-z0-9]*/g) ?? []).flatMap((token) => {
    const alphabeticPrefix = token.match(/^[a-z]+/)?.[0] ?? token;

    return alphabeticPrefix !== token && alphabeticPrefix.length > 1
      ? [token, alphabeticPrefix]
      : [token];
  }).filter((token) => token.length > 1);
}

/**
 * Determine whether one icon key should be considered a match for a model.
 *
 * Why: providers often append version numbers directly after the brand name,
 * for example `qwen3.5-plus`, so we intentionally allow prefix matches in
 * addition to exact token matches.
 *
 * @param normalizedModel The lowercased model identifier.
 * @param modelTokens Parsed brand-like tokens extracted from the model.
 * @param iconKey The icon key derived from one `public/llms/*.svg` file name.
 * @returns Whether the icon should be tried for this model.
 */
function matchesIconKey(
  normalizedModel: string,
  modelTokens: string[],
  iconKey: string,
): boolean {
  if (normalizedModel.includes(iconKey)) {
    return true;
  }

  return modelTokens.some((token) => token === iconKey || token.startsWith(iconKey));
}

/**
 * Build a prioritized list of icon candidate paths for one model identifier.
 *
 * @param model The provider model identifier configured on the LLM.
 * @returns Candidate public asset paths ordered from most to least likely.
 */
export function getLLMBrandIconCandidates(
  model: string | null | undefined,
): string[] {
  const normalizedModel = model?.toLowerCase().trim();
  if (!normalizedModel) {
    return [];
  }

  const modelTokens = getModelBrandTokens(normalizedModel);
  const orderedBrandKeys = new Set<string>();

  for (const iconKey of LLM_ICON_KEYS) {
    if (matchesIconKey(normalizedModel, modelTokens, iconKey)) {
      orderedBrandKeys.add(iconKey);
    }
  }

  for (const token of modelTokens) {
    const alias = LLM_BRAND_ALIASES[token];
    if (alias) {
      orderedBrandKeys.add(alias);
    }

    for (const [providerKey, brandKey] of Object.entries(LLM_BRAND_ALIASES)) {
      if (token.startsWith(providerKey)) {
        orderedBrandKeys.add(brandKey);
      }
    }
  }

  return Array.from(orderedBrandKeys, (brandKey) => `/llms/${brandKey}.svg`);
}

/**
 * Resolve the most likely brand icon path from a model identifier.
 *
 * @param model The provider model identifier configured on the LLM.
 * @returns The first candidate icon path, or null when the model does not
 *   expose any brand-like tokens.
 */
export function getLLMBrandIconPath(
  model: string | null | undefined,
): string | null {
  return getLLMBrandIconCandidates(model)[0] ?? null;
}
