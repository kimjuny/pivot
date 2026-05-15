import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  Container,
  Cog,
  Database,
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileCog,
  FileImage,
  FileJson,
  FileSpreadsheet,
  FileText,
  FileVideo,
  GitBranch,
  Lock,
  Package,
  Shield,
} from "lucide-react";

/** Maps file extensions (lowercase, no dot) to their corresponding Lucide icon. */
const extensionIcons: Record<string, LucideIcon> = {
  // Code
  ts: FileCode,
  tsx: FileCode,
  js: FileCode,
  jsx: FileCode,
  py: FileCode,
  go: FileCode,
  rs: FileCode,
  java: FileCode,
  c: FileCode,
  cpp: FileCode,
  h: FileCode,
  rb: FileCode,
  php: FileCode,
  swift: FileCode,
  kt: FileCode,
  scala: FileCode,
  lua: FileCode,
  sh: FileCode,
  bash: FileCode,
  zsh: FileCode,
  fish: FileCode,

  // Web markup / stylesheets
  html: FileCode,
  htm: FileCode,
  css: FileCode,
  scss: FileCode,
  sass: FileCode,
  less: FileCode,
  vue: FileCode,
  svelte: FileCode,

  // Data / config
  json: FileJson,
  jsonc: FileJson,
  yaml: FileCog,
  yml: FileCog,
  toml: FileCog,
  xml: FileCode,
  ini: FileCog,
  conf: FileCog,
  cfg: FileCog,

  // Document / text
  md: FileText,
  markdown: FileText,
  txt: FileText,
  log: FileText,
  pdf: FileText,
  doc: FileText,
  docx: FileText,
  rtf: FileText,

  // Spreadsheet
  csv: FileSpreadsheet,
  xls: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  tsv: FileSpreadsheet,

  // Presentation
  ppt: FileText,
  pptx: FileText,

  // Image
  png: FileImage,
  jpg: FileImage,
  jpeg: FileImage,
  gif: FileImage,
  svg: FileImage,
  webp: FileImage,
  bmp: FileImage,
  ico: FileImage,
  tiff: FileImage,

  // Video
  mp4: FileVideo,
  avi: FileVideo,
  mov: FileVideo,
  mkv: FileVideo,
  webm: FileVideo,
  flv: FileVideo,

  // Audio
  mp3: FileAudio,
  wav: FileAudio,
  flac: FileAudio,
  aac: FileAudio,
  ogg: FileAudio,
  m4a: FileAudio,

  // Archive
  zip: FileArchive,
  tar: FileArchive,
  gz: FileArchive,
  rar: FileArchive,
  "7z": FileArchive,
  bz2: FileArchive,
  xz: FileArchive,

  // Database
  sql: Database,
  db: Database,
  sqlite: Database,
  sqlite3: Database,
};

/**
 * Returns the appropriate Lucide icon component for a given filename.
 *
 * Matches by special filename patterns first, then by extension, then
 * falls back to the generic {@link File} icon.
 */
export function getFileIcon(filename: string): LucideIcon {
  const lower = filename.toLowerCase();

  // Special filename patterns (exact or prefix match)
  if (lower === "dockerfile" || lower.startsWith("docker-compose")) {
    return Container;
  }
  if (lower === "makefile" || lower === "gnumakefile") {
    return Cog;
  }
  if (
    lower.startsWith("readme") ||
    lower.startsWith("changelog") ||
    lower.startsWith("contributing")
  ) {
    return BookOpen;
  }
  if (lower.startsWith("license")) {
    return Shield;
  }
  if (lower.startsWith(".env")) {
    return Lock;
  }
  if (lower === ".gitignore" || lower === ".gitattributes" || lower === ".gitmodules") {
    return GitBranch;
  }
  if (lower === "package.json" || lower === "tsconfig.json") {
    return Package;
  }

  // Extension-based lookup
  const dotIndex = lower.lastIndexOf(".");
  if (dotIndex >= 0) {
    const ext = lower.slice(dotIndex + 1);
    const icon = extensionIcons[ext];
    if (icon) {
      return icon;
    }
  }

  return File;
}
