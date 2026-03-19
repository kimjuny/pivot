import { mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const llmIconsDirectory = path.join(projectRoot, "public", "llms");
const generatedDirectory = path.join(projectRoot, "src", "generated");
const generatedFilePath = path.join(generatedDirectory, "llmIconManifest.ts");

/**
 * Return the sorted list of icon key names derived from `public/llms/*.svg`.
 *
 * Why: the icon file name is the source of truth that contributors control when
 * they add a new brand asset, so the runtime matching logic should consume the
 * same list instead of duplicating it in handwritten code.
 *
 * @returns {Promise<string[]>} Icon keys sorted by descending length so more
 *   specific names match before shorter substrings.
 */
async function getLlmIconKeys() {
  const entries = await readdir(llmIconsDirectory, { withFileTypes: true });

  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".svg"))
    .map((entry) => path.basename(entry.name, ".svg").toLowerCase())
    .sort((left, right) => right.length - left.length || left.localeCompare(right));
}

/**
 * Persist the generated TypeScript module consumed by frontend code.
 *
 * @param {string[]} iconKeys The icon file names without their `.svg` suffix.
 * @returns {Promise<void>}
 */
async function writeManifest(iconKeys) {
  const fileContent = `/**
 * Auto-generated from \`public/llms/*.svg\`.
 * Do not edit manually; update the icon files and rerun the generator instead.
 */
export const LLM_ICON_KEYS = ${JSON.stringify(iconKeys, null, 2)} as const;
`;

  await mkdir(generatedDirectory, { recursive: true });
  await writeFile(generatedFilePath, fileContent, "utf8");
}

const iconKeys = await getLlmIconKeys();
await writeManifest(iconKeys);
