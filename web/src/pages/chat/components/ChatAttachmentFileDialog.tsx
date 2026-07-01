import { useCallback, useEffect, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";

import DraggableDialog from "@/components/DraggableDialog";
import {
  isDesktop,
  saveBlobWithNativeDialog,
} from "@/desktop/desktop-adapter";
import { fetchChatFileBlob } from "@/utils/api";

import type { ChatAttachment } from "../types";
import { FileRenderer } from "./file-renderer/FileRenderer";
import { resolveRendererKind } from "./file-renderer/resolveRendererKind";

interface ChatAttachmentFileDialogProps {
  attachment: ChatAttachment | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Opens a user-uploaded chat attachment inside a draggable window. Rendering is
 * delegated to {@link FileRenderer} (shared with assistant attachments) so both
 * code paths support the same set of file types.
 */
export function ChatAttachmentFileDialog({
  attachment,
  open,
  onOpenChange,
}: ChatAttachmentFileDialogProps) {
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

        const kind = resolveRendererKind({
          extension: attachment.extension,
          mimeType: attachment.mimeType,
          filename: attachment.originalName,
        });
        if (kind === "markdown" || kind === "text") {
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
              <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
                {errorMessage}
              </div>
            </div>
          ) : attachment && fileBlob && objectUrl ? (
            <FileRenderer
              blob={fileBlob}
              objectUrl={objectUrl}
              displayName={attachment.originalName}
              extension={attachment.extension}
              mimeType={attachment.mimeType}
              textContent={textContent}
            />
          ) : null}
        </div>
      </div>
    </DraggableDialog>
  );
}
