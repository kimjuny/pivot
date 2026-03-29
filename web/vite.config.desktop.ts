/// <reference types="vitest" />
import { mkdir, readdir, writeFile } from 'node:fs/promises'
import path from 'path'
import { defineConfig, type Plugin, type PluginOption } from 'vite'
import react from '@vitejs/plugin-react'

function resolveReactPlugin(): PluginOption {
  const pluginFactory: unknown = react
  if (typeof pluginFactory !== 'function') {
    throw new TypeError('Expected @vitejs/plugin-react to export a plugin factory')
  }
  return (pluginFactory as () => PluginOption)()
}

function resolveLlmIconManifestPlugin(): PluginOption {
  const pluginFactory: unknown = llmIconManifestPlugin
  if (typeof pluginFactory !== 'function') {
    throw new TypeError('Expected llmIconManifestPlugin to export a plugin factory')
  }
  return (pluginFactory as () => PluginOption)()
}

async function generateLlmIconManifest(projectRoot: string): Promise<void> {
  const llmIconsDirectory = path.join(projectRoot, 'public', 'llms')
  const entries = await readdir(llmIconsDirectory, { withFileTypes: true })
  const iconKeys = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith('.svg'))
    .map((entry) => path.basename(entry.name, '.svg').toLowerCase())
    .sort((left, right) => right.length - left.length || left.localeCompare(right))
  const generatedDirectory = path.join(projectRoot, 'src', 'generated')
  const generatedFilePath = path.join(generatedDirectory, 'llmIconManifest.ts')
  const fileContent = `/**
 * Auto-generated from \`public/llms/*.svg\`.
 * Do not edit manually; update the icon files and rerun the generator instead.
 */
export const LLM_ICON_KEYS = ${JSON.stringify(iconKeys, null, 2)} as const;
`

  await mkdir(generatedDirectory, { recursive: true })
  await writeFile(generatedFilePath, fileContent, 'utf8')
}

function llmIconManifestPlugin(): Plugin {
  let projectRoot = ''

  return {
    name: 'pivot-llm-icon-manifest',
    configResolved(config) {
      projectRoot = config.root
    },
    async buildStart() {
      await generateLlmIconManifest(projectRoot)
    },
  }
}

/**
 * Desktop Vite configuration.
 *
 * Builds the Consumer-only frontend for the Tauri desktop shell.
 * Outputs to dist-desktop/ and uses desktop.html as the entry point.
 *
 * Dev mode  — Vite dev server proxies `/api` to the backend (no CORS).
 * Prod mode — Tauri HTTP plugin routes requests through Rust's reqwest.
 */
export default defineConfig({
  plugins: [resolveReactPlugin(), resolveLlmIconManifestPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL || 'http://localhost:8003',
        changeOrigin: true,
        secure: false,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            if (req.url?.includes('/stream')) {
              proxyReq.setHeader('Connection', 'keep-alive');
              proxyReq.setHeader('Cache-Control', 'no-cache');
            }
          });
          proxy.on('proxyRes', (proxyRes, req) => {
            if (req.url?.includes('/stream')) {
              proxyRes.headers['cache-control'] = 'no-cache';
              proxyRes.headers['connection'] = 'keep-alive';
            }
          });
        },
      },
    },
  },
  build: {
    outDir: 'dist-desktop',
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'desktop.html'),
      },
    },
  },
  envFile: ['.env.desktop', '.env'],
})
