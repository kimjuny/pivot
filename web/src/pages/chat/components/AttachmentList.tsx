import { Loader2, Trash2, XCircle } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import type { ChatAttachment, PendingUploadItem } from "../types";
import { AttachmentThumbnail } from "./AttachmentThumbnail";

interface AttachmentListProps {
  attachments?: ChatAttachment[];
  variant?: "message" | "composer";
  onRemovePendingFile?: (clientId: string) => void | Promise<void>;
}

/**
 * Renders message attachments and composer queue thumbnails with shared visual treatment.
 */
export function AttachmentList({
  attachments,
  variant = "message",
  onRemovePendingFile,
}: AttachmentListProps) {
  if (!attachments || attachments.length === 0) {
    return null;
  }

  if (variant === "composer") {
    return (
      <div className="flex flex-wrap gap-2 px-3 pt-3">
        {attachments.map((attachment) => {
          const queueItem = attachment as PendingUploadItem;
          const baseControlClassName =
            "absolute -top-1.5 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-transparent transition-colors";
          const statusIcon =
            queueItem.status === "uploading" ? (
              <span
                className={`${baseControlClassName} -left-1.5 text-muted-foreground`}
                aria-label="Attachment is processing"
              >
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              </span>
            ) : queueItem.status === "error" ? (
              <TooltipProvider delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span
                      className={`${baseControlClassName} -left-1.5 cursor-help text-destructive`}
                      aria-label="Attachment failed"
                      tabIndex={0}
                    >
                      <XCircle className="h-3.5 w-3.5" />
                    </span>
                  </TooltipTrigger>
                  <TooltipContent
                    side="top"
                    className="max-w-64 whitespace-pre-wrap break-words text-xs leading-relaxed"
                  >
                    {queueItem.errorMessage || "Upload failed"}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : null;

          return (
            <div key={queueItem.clientId} className="group relative h-12 w-12">
              <div
                className={`relative flex h-full w-full overflow-hidden rounded-lg border bg-muted ${
                  queueItem.status === "error"
                    ? "border-destructive/60 bg-destructive/[0.035] shadow-[0_0_0_1px_oklch(var(--destructive)/0.18)]"
                    : "border-border/80"
                }`}
              >
                <AttachmentThumbnail
                  attachment={queueItem}
                  alt={queueItem.originalName}
                />
                <div className="absolute inset-x-0 bottom-0 bg-background/88 px-1.5 py-1 text-[9px] leading-tight">
                  <div className="truncate text-foreground">
                    {queueItem.originalName}
                  </div>
                </div>
              </div>
              {statusIcon}
              <button
                type="button"
                onClick={() => {
                  void onRemovePendingFile?.(queueItem.clientId);
                }}
                className={`${baseControlClassName} -right-1.5 pointer-events-none text-destructive/80 opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 hover:text-destructive`}
                title="Remove attachment"
                aria-label={`Remove ${queueItem.originalName}`}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {attachments.map((attachment) => (
        <div
          key={attachment.fileId}
          className="overflow-hidden rounded-xl border border-border bg-background/70"
        >
          <div className="h-28 w-28">
            <AttachmentThumbnail
              attachment={attachment}
              alt={attachment.originalName}
            />
          </div>
          <div className="max-w-28 border-t border-border/60 px-2 py-1 text-[10px] text-muted-foreground">
            <div className="truncate">{attachment.originalName}</div>
            {attachment.kind === "document" && (
              <div className="truncate uppercase">
                {attachment.extension}
                {attachment.pageCount ? ` · ${attachment.pageCount}p` : ""}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
