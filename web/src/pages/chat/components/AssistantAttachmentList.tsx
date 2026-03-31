import { useMemo, useState } from "react";
import {
  Download,
  Eye,
  FileSpreadsheet,
  FileText,
  ImagePlus,
  Presentation,
} from "@/lib/lucide";

import type { AssistantAttachment } from "../types";
import { AssistantAttachmentDialog } from "./AssistantAttachmentDialog";

interface AssistantAttachmentListProps {
  attachments?: AssistantAttachment[];
}

/**
 * Formats bytes into compact labels so artifact cards stay easy to scan.
 */
function formatAttachmentSize(sizeBytes: number): string {
  if (sizeBytes < 1024) {
    return `${sizeBytes}B`;
  }
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)}KB`;
  }
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)}MB`;
}

/**
 * Converts attachment render kinds into user-facing labels with calmer typography.
 */
function formatAttachmentKindLabel(attachment: AssistantAttachment): string {
  if (attachment.renderKind === "download") {
    return "Raw";
  }
  if (attachment.renderKind === "text") {
    return "Text";
  }
  if (attachment.renderKind === "markdown") {
    return "Markdown";
  }
  if (attachment.renderKind === "pdf") {
    return "PDF";
  }
  if (attachment.renderKind === "image") {
    return "Image";
  }

  return attachment.renderKind;
}

/**
 * Only previewable formats should behave like action buttons in the answer timeline.
 */
function isPreviewableAttachment(attachment: AssistantAttachment): boolean {
  return attachment.renderKind !== "download";
}

/**
 * Picks a recognizable icon for one assistant-generated attachment card.
 */
function getAttachmentIcon(attachment: AssistantAttachment) {
  if (attachment.renderKind === "image") {
    return <ImagePlus className="h-4 w-4 text-info" />;
  }
  if (attachment.renderKind === "pdf") {
    return <Eye className="h-4 w-4 text-danger" />;
  }
  if (attachment.extension === "pptx") {
    return <Presentation className="h-4 w-4 text-warning" />;
  }
  if (attachment.extension === "xlsx") {
    return <FileSpreadsheet className="h-4 w-4 text-success" />;
  }
  if (attachment.renderKind === "download") {
    return <Download className="h-4 w-4 text-muted-foreground" />;
  }
  return <FileText className="h-4 w-4 text-primary" />;
}

/**
 * Renders assistant-generated artifact cards under one final answer.
 */
export function AssistantAttachmentList({
  attachments,
}: AssistantAttachmentListProps) {
  const [activeAttachment, setActiveAttachment] =
    useState<AssistantAttachment | null>(null);
  const normalizedAttachments = useMemo(
    () => attachments ?? [],
    [attachments],
  );

  if (normalizedAttachments.length === 0) {
    return null;
  }

  return (
    <>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {normalizedAttachments.map((attachment) => (
          isPreviewableAttachment(attachment) ? (
            <button
              key={attachment.attachmentId}
              type="button"
              onClick={() => setActiveAttachment(attachment)}
              className="group flex min-w-[220px] max-w-[280px] flex-1 items-center rounded-xl border border-border/80 bg-muted/20 px-3 py-2.5 text-left transition-colors hover:border-primary/35 hover:bg-muted/35"
              aria-label={`Open ${attachment.displayName}`}
            >
              <div className="mr-2.5 rounded-lg border border-border/70 bg-background p-1.5">
                {getAttachmentIcon(attachment)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold leading-tight text-foreground">
                  {attachment.displayName}
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  {formatAttachmentKindLabel(attachment)} ·{" "}
                  {formatAttachmentSize(attachment.sizeBytes)}
                </div>
              </div>
            </button>
          ) : (
            <div
              key={attachment.attachmentId}
              className="flex min-w-[220px] max-w-[280px] flex-1 items-center rounded-xl border border-border/80 bg-muted/20 px-3 py-2.5"
            >
              <div className="mr-2.5 rounded-lg border border-border/70 bg-background p-1.5">
                {getAttachmentIcon(attachment)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold leading-tight text-foreground">
                  {attachment.displayName}
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  {formatAttachmentKindLabel(attachment)} ·{" "}
                  {formatAttachmentSize(attachment.sizeBytes)}
                </div>
              </div>
            </div>
          )
        ))}
      </div>

      <AssistantAttachmentDialog
        attachment={activeAttachment}
        open={activeAttachment !== null}
        onOpenChange={(open) => {
          if (!open) {
            setActiveAttachment(null);
          }
        }}
      />
    </>
  );
}
