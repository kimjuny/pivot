import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { Check, Loader2, Pencil } from "@/lib/lucide";
import { toast } from "sonner";

import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTheme } from "@/lib/use-theme";
import {
  fetchChatFileBlob,
  fetchWorkspaceTextFile,
  updateWorkspaceTextFile,
} from "@/utils/api";

import type { ChatAttachment } from "../types";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface AttachmentPreviewDialogProps {
  attachment: ChatAttachment | null;
  currentSessionId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Resolve the active app theme to the Monaco theme variant expected by the editor.
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
 * Map uploaded text-like files to the closest Monaco language for live editing.
 */
function getAttachmentEditorLanguage(attachment: ChatAttachment): string {
  const extension = attachment.extension.toLowerCase();

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
 * Opens one live workspace file from chat history so upload cards point at the
 * current workspace asset instead of a stale snapshot copy.
 */
export function AttachmentPreviewDialog({
  attachment,
  currentSessionId,
  open,
  onOpenChange,
}: AttachmentPreviewDialogProps) {
  const monacoTheme = useResolvedMonacoTheme();
  const [src, setSrc] = useState<string | null>(attachment?.previewUrl ?? null);
  const [textContent, setTextContent] = useState<string>("");
  const [draftContent, setDraftContent] = useState<string>("");
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [hasLoadError, setHasLoadError] = useState<boolean>(false);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(
    null,
  );
  const renderKind =
    attachment === null
      ? null
      : attachment.kind === "image" || attachment.mimeType.startsWith("image/")
        ? "image"
        : attachment.extension.toLowerCase() === "md" ||
            attachment.mimeType === "text/markdown" ||
            attachment.mimeType === "text/x-markdown"
          ? "markdown"
          : attachment.extension.toLowerCase() === "pdf" ||
              attachment.mimeType === "application/pdf"
            ? "pdf"
            : attachment.mimeType.startsWith("text/") ||
                attachment.mimeType === "application/json" ||
                attachment.mimeType.includes("javascript") ||
                attachment.mimeType.includes("ecmascript") ||
                attachment.mimeType.includes("xml")
              ? "text"
              : "download";
  const isEditableAttachment = Boolean(
    currentSessionId !== null &&
      attachment?.workspaceRelativePath &&
      (renderKind === "markdown" || renderKind === "text"),
  );

  useEffect(() => {
    if (!open || !attachment) {
      setSrc(attachment?.previewUrl ?? null);
      setTextContent("");
      setDraftContent("");
      setIsEditing(false);
      setIsSaving(false);
      setHasLoadError(false);
      setNaturalSize(null);
      return;
    }

    if (attachment.previewUrl && renderKind === "image") {
      setSrc(attachment.previewUrl);
      setTextContent("");
      setHasLoadError(false);
      setNaturalSize(null);
      return;
    }

    const controller = new AbortController();
    let objectUrl: string | null = null;

    const loadImage = async () => {
      try {
        setHasLoadError(false);
        setNaturalSize(null);
        setTextContent("");
        setDraftContent("");
        if (
          currentSessionId &&
          attachment.workspaceRelativePath &&
          (renderKind === "text" || renderKind === "markdown")
        ) {
          const file = await fetchWorkspaceTextFile(
            currentSessionId,
            attachment.workspaceRelativePath,
            controller.signal,
          );
          setTextContent(file.content);
          setDraftContent(file.content);
          setSrc(null);
          return;
        }
        const blob = await fetchChatFileBlob(attachment.fileId, controller.signal);
        if (renderKind === "text" || renderKind === "markdown") {
          const nextText = await blob.text();
          setTextContent(nextText);
          setDraftContent(nextText);
          setSrc(null);
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        console.error("Failed to load image preview:", error);
        setHasLoadError(true);
      }
    };

    void loadImage();

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [attachment, currentSessionId, open, renderKind]);

  const handleSave = async () => {
    if (
      !attachment?.workspaceRelativePath ||
      currentSessionId === null ||
      !isEditableAttachment
    ) {
      return;
    }

    try {
      setIsSaving(true);
      await updateWorkspaceTextFile(
        currentSessionId,
        attachment.workspaceRelativePath,
        draftContent,
      );
      setTextContent(draftContent);
      setIsEditing(false);
      toast.success(`Saved ${attachment.originalName}`);
    } catch (error) {
      console.error("Failed to save live workspace file:", error);
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to save this workspace file.",
      );
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay className="z-[2147483646]" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-[2147483647] -translate-x-1/2 -translate-y-1/2 outline-none">
          <DialogHeader className="sr-only">
            <DialogTitle>Live workspace file preview</DialogTitle>
            <DialogDescription>
              Displays the current workspace-backed file for this chat attachment.
            </DialogDescription>
          </DialogHeader>

          <div className="flex max-h-[96vh] w-[min(96vw,960px)] flex-col overflow-hidden rounded-2xl border border-border/70 bg-background shadow-2xl">
            <div className="border-b border-border/70 px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground">
                    {attachment?.originalName ?? "Attachment"}
                  </div>
                  {attachment?.workspaceRelativePath ? (
                    <div className="mt-1 font-mono text-xs text-muted-foreground">
                      /workspace/{attachment.workspaceRelativePath}
                    </div>
                  ) : null}
                </div>
                {isEditableAttachment ? (
                  <div className="flex items-center gap-2">
                    {isEditing ? (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            setDraftContent(textContent);
                            setIsEditing(false);
                          }}
                          className="rounded-md border border-border/70 px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            void handleSave();
                          }}
                          disabled={isSaving}
                          className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Check className="h-3.5 w-3.5" />
                          {isSaving ? "Saving..." : "Save"}
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setIsEditing(true)}
                        className="inline-flex items-center gap-1 rounded-md border border-border/70 px-2 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </button>
                    )}
                  </div>
                ) : null}
              </div>
            </div>
            <div className="flex min-h-[320px] max-h-[calc(96vh-72px)] items-center justify-center overflow-auto p-4">
              {renderKind === "image" && src ? (
                <img
                  src={src}
                  alt={attachment?.originalName ?? "Attachment"}
                  className="block h-auto w-auto max-h-[96vh] max-w-[96vw] shadow-2xl"
                  style={
                    naturalSize
                      ? {
                          width: `${naturalSize.width}px`,
                          height: `${naturalSize.height}px`,
                        }
                      : undefined
                  }
                  onLoad={(event) => {
                    setNaturalSize({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    });
                  }}
                />
              ) : renderKind === "markdown" ? (
                <div className="mx-auto w-full max-w-5xl px-4 md:px-8 lg:px-12">
                  {isEditing ? (
                    <div className="h-[70vh] w-full overflow-hidden rounded-lg border border-border/70 bg-muted/20">
                      <Editor
                        height="100%"
                        language="markdown"
                        value={draftContent}
                        theme={monacoTheme}
                        onChange={(value) => setDraftContent(value ?? "")}
                        loading={
                          <div className="flex h-full min-h-[60vh] items-center justify-center text-muted-foreground">
                            <Loader2 className="h-5 w-5 animate-spin" />
                          </div>
                        }
                        options={{
                          automaticLayout: true,
                          fontSize: 13,
                          minimap: { enabled: false },
                          scrollBeyondLastLine: false,
                          wordWrap: "on",
                        }}
                      />
                    </div>
                  ) : (
                    <MarkdownRenderer content={textContent} variant="document" />
                  )}
                </div>
              ) : renderKind === "text" ? (
                <div className="h-[70vh] w-full overflow-hidden rounded-lg border border-border/70 bg-muted/20">
                  <Editor
                    height="100%"
                    language={
                      attachment
                        ? getAttachmentEditorLanguage(attachment)
                        : "plaintext"
                    }
                    value={isEditing ? draftContent : textContent}
                    theme={monacoTheme}
                    onChange={(value) => {
                      if (isEditing) {
                        setDraftContent(value ?? "");
                      }
                    }}
                    loading={
                      <div className="flex h-full min-h-[60vh] items-center justify-center text-muted-foreground">
                        <Loader2 className="h-5 w-5 animate-spin" />
                      </div>
                    }
                    options={{
                      automaticLayout: true,
                      domReadOnly: !isEditing,
                      fontSize: 13,
                      lineNumbers: "on",
                      minimap: { enabled: false },
                      readOnly: !isEditing,
                      renderLineHighlight: "none",
                      renderWhitespace: "selection",
                      scrollBeyondLastLine: false,
                      wordWrap: "on",
                    }}
                  />
                </div>
              ) : renderKind === "pdf" && src ? (
                <iframe
                  src={src}
                  title={attachment?.originalName ?? "Attachment"}
                  className="h-[70vh] w-full rounded-lg border border-border/70 bg-white"
                />
              ) : renderKind === "download" ? (
                <div className="flex h-full min-h-40 max-w-md flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border/70 bg-muted/20 px-6 text-center">
                  <p className="text-sm text-foreground">
                    This live workspace file does not have an inline preview yet.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    It still points at the current file under your workspace, not
                    a frozen snapshot.
                  </p>
                </div>
              ) : hasLoadError ? (
                <div className="rounded-lg bg-background/95 px-6 py-4 text-center text-sm text-muted-foreground shadow-2xl">
                  Unable to load this live file preview.
                </div>
              ) : (
                <div className="rounded-lg bg-background/95 p-4 shadow-2xl">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              )}
            </div>
          </div>
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
}
