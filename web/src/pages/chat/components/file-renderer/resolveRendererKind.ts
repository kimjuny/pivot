/**
 * Renderer kinds supported by the attachment preview dialog.
 *
 * The frontend decides how to render an attachment from its extension and MIME
 * type via {@link resolveRendererKind}. This is deliberately independent of the
 * backend `render_kind` hint so the assistant-attachment and user-attachment
 * code paths share a single source of truth, and legacy rows keep rendering
 * correctly as new kinds are introduced.
 */
export type RendererKind =
  | "markdown"
  | "text"
  | "image"
  | "pdf"
  | "docx"
  | "spreadsheet"
  | "video"
  | "unknown";

const MARKDOWN_EXTENSIONS = new Set(["md", "markdown"]);
const MARKDOWN_MIME_TYPES = new Set(["text/markdown", "text/x-markdown"]);

const DOCX_EXTENSIONS = new Set(["docx"]);
const DOCX_MIME_KEYWORD = "wordprocessingml.document";

const SPREADSHEET_EXTENSIONS = new Set(["xlsx", "xls", "csv"]);
const SPREADSHEET_MIME_TYPES = new Set([
  "text/csv",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]);

// Mirrors server-side _TEXT_EXTENSIONS so extensionless code/text files route
// to the Monaco renderer instead of falling through to "unknown".
const TEXT_EXTENSIONS = new Set([
  "bat",
  "c",
  "cc",
  "cfg",
  "conf",
  "cpp",
  "css",
  "env",
  "go",
  "h",
  "hpp",
  "htm",
  "html",
  "ini",
  "java",
  "js",
  "json",
  "jsonl",
  "jsx",
  "log",
  "lua",
  "py",
  "rb",
  "rs",
  "scss",
  "sh",
  "sql",
  "svg",
  "text",
  "toml",
  "ts",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
  "zsh",
]);
const TEXT_FILENAMES = new Set(["dockerfile", "makefile", ".env"]);
const TEXT_MIME_TYPES = new Set([
  "application/ecmascript",
  "application/javascript",
  "application/json",
  "application/sql",
  "application/toml",
  "application/x-httpd-php",
  "application/x-python-code",
  "application/x-sh",
  "application/x-shellscript",
  "application/x-yaml",
]);

function isTextLike(extension: string, mime: string, filename: string): boolean {
  if (TEXT_EXTENSIONS.has(extension)) {
    return true;
  }
  if (TEXT_FILENAMES.has(filename)) {
    return true;
  }
  if (mime.startsWith("text/")) {
    return true;
  }
  return TEXT_MIME_TYPES.has(mime);
}

interface ResolveRendererKindArgs {
  extension: string;
  mimeType: string;
  /** Lower-cased file name (without path). Used to catch extensionless text
   * files like `dockerfile` / `makefile`. Optional but recommended. */
  filename?: string;
}

/**
 * Pick the renderer for one attachment from its metadata alone.
 *
 * Branch order is significant: binary and rich-document formats must be checked
 * before `text`/`markdown`, otherwise `csv` (MIME `text/csv`) and the occasional
 * markdown file guessed as `text/plain` would be misrouted.
 */
export function resolveRendererKind({
  extension,
  mimeType,
  filename,
}: ResolveRendererKindArgs): RendererKind {
  const ext = extension.toLowerCase();
  const mime = mimeType.toLowerCase();
  const name = (filename ?? "").toLowerCase();

  if (ext === "pdf" || mime === "application/pdf") {
    return "pdf";
  }
  if (DOCX_EXTENSIONS.has(ext) || mime.includes(DOCX_MIME_KEYWORD)) {
    return "docx";
  }
  if (
    SPREADSHEET_EXTENSIONS.has(ext) ||
    SPREADSHEET_MIME_TYPES.has(mime)
  ) {
    return "spreadsheet";
  }
  if (mime.startsWith("video/")) {
    return "video";
  }
  if (mime.startsWith("image/")) {
    return "image";
  }
  if (
    MARKDOWN_EXTENSIONS.has(ext) ||
    MARKDOWN_MIME_TYPES.has(mime)
  ) {
    return "markdown";
  }
  if (isTextLike(ext, mime, name)) {
    return "text";
  }
  return "unknown";
}
