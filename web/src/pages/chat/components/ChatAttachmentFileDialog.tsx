import { useCallback, useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";

import DraggableDialog from "@/components/DraggableDialog";
import {
  isDesktop,
  saveBlobWithNativeDialog,
} from "@/desktop/desktop-adapter";
import { useTheme } from "@/lib/use-theme";
import { fetchChatFileBlob } from "@/utils/api";

import type { ChatAttachment } from "../types";

/** Resolve the app theme to the Monaco theme identifier. */
function useResolvedMonacoTheme(): "vs-dark" | "light" {
  const { theme } = useTheme();

  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "vs-dark"
      : "light";
  }

  return theme === "dark" ? "vs-dark" : "light";
}

/** Map a file extension to a Monaco language identifier. */
function getFileLanguage(attachment: ChatAttachment): string {
  const ext = attachment.extension.toLowerCase();
  const name = attachment.originalName.toLowerCase();

  if (name === "dockerfile") return "dockerfile";
  if (name === "makefile") return "plaintext";

  const map: Record<string, string> = {
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

  if (ext in map) return map[ext];

  if (attachment.mimeType === "application/json") return "json";
  if (attachment.mimeType.startsWith("text/html")) return "html";
  if (attachment.mimeType.startsWith("text/css")) return "css";
  if (
    attachment.mimeType.includes("javascript") ||
    attachment.mimeType.includes("ecmascript")
  ) {
    return "javascript";
  }

  return "plaintext";
}

/**
 * Quick heuristic to decide whether a file extension is worth showing in a
 * text editor. Binary formats (images, audio, video, archives) return false.
 */
function isTextLike(attachment: ChatAttachment): boolean {
  const binary = [
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "svg",
    "bmp",
    "ico",
    "mp3",
    "wav",
    "ogg",
    "mp4",
    "webm",
    "avi",
    "mov",
    "zip",
    "tar",
    "gz",
    "bz2",
    "7z",
    "rar",
    "exe",
    "dll",
    "so",
    "dylib",
    "woff",
    "woff2",
    "ttf",
    "otf",
    "eot",
    "pdf",
    "doc",
    "docx",
    "pptx",
    "xlsx",
  ];
  if (binary.includes(attachment.extension.toLowerCase())) return false;

  if (attachment.mimeType.startsWith("text/")) return true;
  if (attachment.mimeType === "application/json") return true;
  if (attachment.mimeType.includes("javascript")) return true;
  if (attachment.mimeType.includes("xml")) return true;

  return true;
}

interface ChatAttachmentFileDialogProps {
  attachment: ChatAttachment | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Opens a user-uploaded chat attachment inside a draggable window with a
 * read-only Monaco editor for text files.
 */
export function ChatAttachmentFileDialog({
  attachment,
  open,
  onOpenChange,
}: ChatAttachmentFileDialogProps) {
  const monacoTheme = useResolvedMonacoTheme();
  const [textContent, setTextContent] = useState("");
  const [fileBlob, setFileBlob] = useState<Blob | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !attachment) {
      setTextContent("");
      setFileBlob(null);
      setObjectUrl(null);
      setIsLoading(false);
      setErrorMessage(null);
      return;
    }

    const controller = new AbortController();
    let nextObjectUrl: string | null = null;

    const load = async () => {
      try {
        setIsLoading(true);
        setErrorMessage(null);
        setTextContent("");
        const blob = await fetchChatFileBlob(
          attachment.fileId,
          controller.signal,
        );
        setFileBlob(blob);
        nextObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(nextObjectUrl);

        if (isTextLike(attachment)) {
          setTextContent(await blob.text());
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("Failed to load chat attachment:", error);
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "Failed to load this file.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    };

    void load();

    return () => {
      controller.abort();
      if (nextObjectUrl) URL.revokeObjectURL(nextObjectUrl);
    };
  }, [attachment, open]);

  const handleDownload = useCallback(async () => {
    if (!attachment || !fileBlob) return;

    if (isDesktop) {
      try {
        const savePath = await saveBlobWithNativeDialog({
          blob: fileBlob,
          suggestedName: attachment.originalName,
          extension: attachment.extension,
          formatLabel: attachment.extension.toUpperCase(),
        });
        if (savePath) toast.success(`Saved ${attachment.originalName}`);
      } catch (error) {
        console.error("Failed to save attachment:", error);
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to save this file.",
        );
      }
      return;
    }

    if (!objectUrl) return;
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = attachment.originalName;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, [attachment, fileBlob, objectUrl]);

  const headerAction =
    attachment && fileBlob ? (
      <button
        type="button"
        onClick={() => void handleDownload()}
        className="inline-flex h-6 w-6 items-center justify-center rounded p-1 transition-colors hover:bg-accent"
        aria-label={`Download ${attachment.originalName}`}
      >
        <Download className="h-3.5 w-3.5 text-foreground" />
      </button>
    ) : null;

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title={attachment?.originalName ?? "Attachment"}
      headerAction={headerAction}
      size="large"
      fullscreenable
    >
      <div className="flex h-full flex-col bg-background">
        <div className="min-h-0 flex-1 overflow-hidden">
          {isLoading ? (
            <div className="flex h-full min-h-40 items-center justify-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : errorMessage ? (
            <div className="p-4">
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {errorMessage}
              </div>
            </div>
          ) : attachment && isTextLike(attachment) ? (
            <div className="h-full min-h-[60vh] bg-muted/20">
              <Editor
                height="100%"
                language={getFileLanguage(attachment)}
                value={textContent}
                theme={monacoTheme}
                loading={
                  <div className="flex h-full min-h-[60vh] items-center justify-center text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin" />
                  </div>
                }
                options={{
                  automaticLayout: true,
                  domReadOnly: true,
                  fontSize: 13,
                  lineNumbers: "on",
                  minimap: { enabled: false },
                  readOnly: true,
                  renderLineHighlight: "none",
                  renderWhitespace: "selection",
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                }}
              />
            </div>
          ) : attachment &&
            attachment.mimeType.startsWith("image/") &&
            objectUrl ? (
            <div className="flex h-full items-center justify-center p-4">
              <img
                src={objectUrl}
                alt={attachment.originalName}
                className="max-h-full max-w-full rounded-lg border border-border/70 bg-muted/20 object-contain"
              />
            </div>
          ) : (
            <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border/70 bg-muted/20 px-6 text-center">
              <p className="text-sm font-medium text-foreground">
                Unsupported file type
              </p>
              <p className="text-xs text-muted-foreground">
                This file cannot be previewed inline. Use the download button in
                the title bar to save it.
              </p>
            </div>
          )}
        </div>
      </div>
    </DraggableDialog>
  );
}
