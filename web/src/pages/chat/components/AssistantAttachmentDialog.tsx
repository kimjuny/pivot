import { useCallback, useEffect, useMemo, useState } from "react";
import Editor from "@monaco-editor/react";
import { Download, Loader2 } from "@/lib/lucide";
import { toast } from "sonner";

import DraggableDialog from "@/components/DraggableDialog";
import {
  isDesktop,
  saveBlobWithNativeDialog,
} from "@/desktop/desktop-adapter";
import { useTheme } from "@/lib/use-theme";
import { fetchTaskAttachmentBlob } from "@/utils/api";

import type { AssistantAttachment } from "../types";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface AssistantAttachmentDialogProps {
  attachment: AssistantAttachment | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Resolve the app theme to the concrete Monaco theme expected by the editor.
 */
function useResolvedMonacoTheme(): "vs-dark" | "light" {
  const { theme } = useTheme();

  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "vs-dark"
      : "light";
  }

  return theme === "dark" ? "vs-dark" : "light";
}

/**
 * Maps one attachment extension to the closest built-in Monaco language.
 */
function getAttachmentEditorLanguage(attachment: AssistantAttachment): string {
  const extension = attachment.extension.toLowerCase();
  const filename = attachment.displayName.toLowerCase();

  if (filename === "dockerfile") {
    return "dockerfile";
  }
  if (filename === "makefile") {
    return "plaintext";
  }

  const languageByExtension: Record<string, string> = {
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

  if (extension in languageByExtension) {
    return languageByExtension[extension];
  }

  if (attachment.mimeType === "application/json") {
    return "json";
  }
  if (attachment.mimeType.startsWith("text/html")) {
    return "html";
  }
  if (attachment.mimeType.startsWith("text/css")) {
    return "css";
  }
  if (
    attachment.mimeType.includes("javascript") ||
    attachment.mimeType.includes("ecmascript")
  ) {
    return "javascript";
  }

  return "plaintext";
}

/**
 * Opens one assistant-generated attachment inside a draggable utility window.
 */
export function AssistantAttachmentDialog({
  attachment,
  open,
  onOpenChange,
}: AssistantAttachmentDialogProps) {
  const monacoTheme = useResolvedMonacoTheme();
  const [textContent, setTextContent] = useState<string>("");
  const [attachmentBlob, setAttachmentBlob] = useState<Blob | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !attachment) {
      setTextContent("");
      setAttachmentBlob(null);
      setObjectUrl(null);
      setIsLoading(false);
      setErrorMessage(null);
      return;
    }

    const controller = new AbortController();
    let nextObjectUrl: string | null = null;

    const loadAttachment = async () => {
      try {
        setIsLoading(true);
        setErrorMessage(null);
        setTextContent("");
        const blob = await fetchTaskAttachmentBlob(
          attachment.attachmentId,
          controller.signal,
        );
        setAttachmentBlob(blob);
        nextObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(nextObjectUrl);

        if (
          attachment.renderKind === "markdown" ||
          attachment.renderKind === "text"
        ) {
          setTextContent(await blob.text());
        }
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        console.error("Failed to load assistant attachment:", error);
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "Failed to load this attachment.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    };

    void loadAttachment();

    return () => {
      controller.abort();
      if (nextObjectUrl) {
        URL.revokeObjectURL(nextObjectUrl);
      }
    };
  }, [attachment, open]);

  const handleDownload = useCallback(async () => {
    if (!attachment || !attachmentBlob) {
      return;
    }

    if (isDesktop) {
      try {
        const savePath = await saveBlobWithNativeDialog({
          blob: attachmentBlob,
          suggestedName: attachment.displayName,
          extension: attachment.extension,
          formatLabel: attachment.renderKind.toUpperCase(),
        });

        if (savePath) {
          toast.success(`Saved ${attachment.displayName}`);
        }
      } catch (error) {
        console.error("Failed to save assistant attachment:", error);
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to save this attachment.",
        );
      }
      return;
    }

    if (!objectUrl) {
      return;
    }

    const downloadLink = document.createElement("a");
    downloadLink.href = objectUrl;
    downloadLink.download = attachment.displayName;
    downloadLink.rel = "noopener";
    document.body.appendChild(downloadLink);
    downloadLink.click();
    downloadLink.remove();
  }, [attachment, attachmentBlob, objectUrl]);

  const headerAction = useMemo(() => {
    if (!attachment || !attachmentBlob || (!isDesktop && !objectUrl)) {
      return null;
    }

    return (
      <button
        type="button"
        onClick={() => {
          void handleDownload();
        }}
        className="inline-flex h-6 w-6 items-center justify-center rounded p-1 transition-colors hover:bg-accent"
        aria-label={`Download ${attachment.displayName}`}
      >
        <Download className="h-3.5 w-3.5 text-foreground" />
      </button>
    );
  }, [attachment, attachmentBlob, handleDownload, objectUrl]);

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title={attachment?.displayName ?? "Attachment"}
      headerAction={headerAction}
      size="large"
      fullscreenable
    >
      <div className="flex h-full flex-col bg-background">
        <div
          className={`min-h-0 flex-1 overflow-auto ${
            attachment?.renderKind === "text" ? "overflow-hidden" : "p-4"
          }`}
        >
          {isLoading ? (
            <div className="flex h-full min-h-40 items-center justify-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : errorMessage ? (
            <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
              {errorMessage}
            </div>
          ) : attachment?.renderKind === "markdown" ? (
            <div className="mx-auto w-full max-w-5xl px-4 md:px-8 lg:px-12">
              <MarkdownRenderer content={textContent} variant="document" />
            </div>
          ) : attachment?.renderKind === "text" ? (
            <div className="h-full min-h-[60vh] bg-muted/20">
              <Editor
                height="100%"
                language={getAttachmentEditorLanguage(attachment)}
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
          ) : attachment?.renderKind === "pdf" ? (
            objectUrl ? (
              <iframe
                src={objectUrl}
                title={attachment.displayName}
                className="h-full min-h-[60vh] w-full rounded-lg border border-border/70 bg-white"
              />
            ) : null
          ) : attachment?.renderKind === "image" ? (
            objectUrl ? (
              <img
                src={objectUrl}
                alt={attachment.displayName}
                className="mx-auto max-h-full max-w-full rounded-lg border border-border/70 bg-muted/20 object-contain"
              />
            ) : null
          ) : (
            <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border/70 bg-muted/20 px-6 text-center">
              <p className="text-sm text-foreground">
                This attachment does not have an inline preview yet.
              </p>
              <p className="text-xs text-muted-foreground">
                Use the download action in the title bar to open the raw file.
              </p>
            </div>
          )}
        </div>
      </div>
    </DraggableDialog>
  );
}
