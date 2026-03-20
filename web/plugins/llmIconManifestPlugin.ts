import path from "node:path";

import type { Plugin } from "vite";

import { generateLlmIconManifest } from "../scripts/generate-llm-icon-manifest.mjs";

/**
 * Keep the generated icon manifest synced with `public/llms` during Vite runs.
 *
 * Why: the app imports a real TypeScript module for broad tooling
 * compatibility, but contributors should still be able to add one SVG file and
 * have the manifest refresh automatically without manual edits.
 */
export function llmIconManifestPlugin(): Plugin {
  let projectRoot = "";

  return {
    name: "pivot-llm-icon-manifest",
    configResolved(config) {
      projectRoot = config.root;
    },
    async buildStart() {
      await generateLlmIconManifest(projectRoot);
    },
    async handleHotUpdate(context) {
      const llmIconsDirectory = `${path.join(projectRoot, "public", "llms")}${path.sep}`;
      if (
        !context.file.startsWith(llmIconsDirectory) ||
        !context.file.endsWith(".svg")
      ) {
        return;
      }

      await generateLlmIconManifest(projectRoot);
      context.server.ws.send({ type: "full-reload" });
    },
  };
}
