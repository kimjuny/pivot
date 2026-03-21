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
    async handleHotUpdate(context) {
      const llmIconsDirectory = `${path.join(projectRoot, 'public', 'llms')}${path.sep}`
      if (
        !context.file.startsWith(llmIconsDirectory) ||
        !context.file.endsWith('.svg')
      ) {
        return
      }

      await generateLlmIconManifest(projectRoot)
      context.server.ws.send({ type: 'full-reload' })
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [resolveReactPlugin(), resolveLlmIconManifestPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    // Allow access from any host (required when running inside a container)
    host: true,
    watch: {
      usePolling: true,
    },
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL || 'http://localhost:8003',
        changeOrigin: true,
        secure: false,
        // Special configuration for SSE (Server-Sent Events)
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            // Preserve streaming for SSE endpoints
            if (req.url?.includes('/stream')) {
              proxyReq.setHeader('Connection', 'keep-alive');
              proxyReq.setHeader('Cache-Control', 'no-cache');
            }
          });
          proxy.on('proxyRes', (proxyRes, req, _res) => {
            // Disable buffering for SSE responses
            if (req.url?.includes('/stream')) {
              proxyRes.headers['cache-control'] = 'no-cache';
              proxyRes.headers['connection'] = 'keep-alive';
            }
          });
        },
      }
    }
  },
  test: {
    globals: true,
    environment: 'happy-dom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    include: ['src/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        'dist/',
      ]
    }
  }
})
