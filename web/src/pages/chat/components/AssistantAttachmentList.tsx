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
    return `${sizeBytes} B`;
  }
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  }
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
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
      <div className="mt-3 flex flex-wrap gap-2">
        {normalizedAttachments.map((attachment) => (
          <button
            key={attachment.attachmentId}
            type="button"
            onClick={() => setActiveAttachment(attachment)}
            className="group flex min-w-[220px] max-w-[280px] flex-1 rounded-xl border border-border/80 bg-muted/20 p-3 text-left transition-colors hover:border-primary/35 hover:bg-muted/35"
            aria-label={`Open ${attachment.displayName}`}
          >
            <div className="mr-3 mt-0.5 rounded-lg border border-border/70 bg-background p-2">
              {getAttachmentIcon(attachment)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-foreground">
                {attachment.displayName}
              </div>
              <div className="mt-1 flex items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                <span>{attachment.renderKind}</span>
                <span>{formatAttachmentSize(attachment.sizeBytes)}</span>
              </div>
            </div>
          </button>
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
