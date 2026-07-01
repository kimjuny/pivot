import { useTheme } from "@/lib/use-theme";

/**
 * Resolve the app theme to the concrete Monaco theme expected by the editor.
 *
 * Shared by every code/text renderer so assistant and user attachments stay in
 * sync with the global light/dark preference.
 */
export function useResolvedMonacoTheme(): "vs-dark" | "light" {
  const { theme } = useTheme();

  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "vs-dark"
      : "light";
  }

  return theme === "dark" ? "vs-dark" : "light";
}

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  bat: "bat",
  c: "c",
  cc: "cpp",
  conf: "ini",
  cpp: "cpp",
  css: "css",
  csv: "plaintext",
  env: "shell",
  go: "go",
  h: "cpp",
  hpp: "cpp",
  htm: "html",
  html: "html",
  ini: "ini",
  java: "java",
  js: "javascript",
  json: "json",
  jsonl: "json",
  jsx: "javascript",
  log: "plaintext",
  lua: "lua",
  md: "markdown",
  py: "python",
  rb: "ruby",
  rs: "rust",
  scss: "scss",
  sh: "shell",
  sql: "sql",
  svg: "xml",
  text: "plaintext",
  toml: "ini",
  ts: "typescript",
  tsx: "typescript",
  txt: "plaintext",
  xml: "xml",
  yaml: "yaml",
  yml: "yaml",
  zsh: "shell",
};

/**
 * Map one attachment to the closest built-in Monaco language identifier.
 *
 * `filename` catches extensionless special files (`dockerfile`, `makefile`);
 * `mimeType` is the fallback when the extension is unknown.
 */
export function getEditorLanguage(
  extension: string,
  filename: string,
  mimeType: string,
): string {
  const ext = extension.toLowerCase();
  const name = filename.toLowerCase();

  if (name === "dockerfile") {
    return "dockerfile";
  }
  if (name === "makefile") {
    return "plaintext";
  }

  if (ext in LANGUAGE_BY_EXTENSION) {
    return LANGUAGE_BY_EXTENSION[ext];
  }

  if (mimeType === "application/json") {
    return "json";
  }
  if (mimeType.startsWith("text/html")) {
    return "html";
  }
  if (mimeType.startsWith("text/css")) {
    return "css";
  }
  if (
    mimeType.includes("javascript") ||
    mimeType.includes("ecmascript")
  ) {
    return "javascript";
  }

  return "plaintext";
}
