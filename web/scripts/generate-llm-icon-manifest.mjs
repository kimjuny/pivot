import { mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const defaultProjectRoot = path.resolve(__dirname, "..");

/**
 * Return the sorted list of icon key names derived from `public/llms/*.svg`.
 *
 * Why: the icon filename is the contributor-controlled keyword that should
 * drive fuzzy matching against LLM model identifiers.
 *
 * @param {string} projectRoot Absolute path to the web project root.
 * @returns {Promise<string[]>} Sorted icon keys, longest first.
 */
export async function getLlmIconKeys(projectRoot = defaultProjectRoot) {
  const llmIconsDirectory = path.join(projectRoot, "public", "llms");
  const entries = await readdir(llmIconsDirectory, { withFileTypes: true });

  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".svg"))
    .map((entry) => path.basename(entry.name, ".svg").toLowerCase())
    .sort((left, right) => right.length - left.length || left.localeCompare(right));
}

/**
 * Persist the generated TypeScript module consumed by frontend code.
 *
 * @param {string[]} iconKeys Icon filenames without the `.svg` suffix.
 * @param {string} projectRoot Absolute path to the web project root.
 * @returns {Promise<void>}
 */
export async function writeManifest(
  iconKeys,
  projectRoot = defaultProjectRoot,
) {
  const generatedDirectory = path.join(projectRoot, "src", "generated");
  const generatedFilePath = path.join(generatedDirectory, "llmIconManifest.ts");
  const fileContent = `/**
 * Auto-generated from \`public/llms/*.svg\`.
 * Do not edit manually; update the icon files and rerun the generator instead.
 */
export const LLM_ICON_KEYS = ${JSON.stringify(iconKeys, null, 2)} as const;
`;

  await mkdir(generatedDirectory, { recursive: true });
  await writeFile(generatedFilePath, fileContent, "utf8");
}

/**
 * Regenerate the icon manifest from current `public/llms` contents.
 *
 * @param {string} projectRoot Absolute path to the web project root.
 * @returns {Promise<string[]>} The keys written into the manifest.
 */
export async function generateLlmIconManifest(
  projectRoot = defaultProjectRoot,
) {
  const iconKeys = await getLlmIconKeys(projectRoot);
  await writeManifest(iconKeys, projectRoot);
  return iconKeys;
}

if (process.argv[1] === __filename) {
  await generateLlmIconManifest();
}
