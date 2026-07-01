import { useMemo, useState } from "react";
import {
  Download,
  Eye,
  FileSpreadsheet,
  FileText,
  FileVideo,
  ImagePlus,
} from "lucide-react";

import type { AssistantAttachment } from "../types";
import { AssistantAttachmentDialog } from "./AssistantAttachmentDialog";
import { resolveRendererKind } from "./file-renderer/resolveRendererKind";

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

const KIND_LABELS: Record<string, string> = {
  markdown: "Markdown",
  text: "Text",
  pdf: "PDF",
  image: "Image",
  docx: "Document",
  spreadsheet: "Sheet",
  video: "Video",
  unknown: "Raw",
};

/**
 * Picks a recognizable icon for one assistant-generated attachment card.
 * Uses the same renderer-kind resolution as the preview dialog so the card and
 * the opened viewer never disagree about what a file is.
 */
function getAttachmentIcon(attachment: AssistantAttachment) {
  const kind = resolveRendererKind({
    extension: attachment.extension,
    mimeType: attachment.mimeType,
    filename: attachment.displayName,
  });
  switch (kind) {
    case "image":
      return <ImagePlus className="h-4 w-4 text-info" />;
    case "pdf":
      return <Eye className="h-4 w-4 text-danger" />;
    case "docx":
      return <FileText className="h-4 w-4 text-primary" />;
    case "spreadsheet":
      return <FileSpreadsheet className="h-4 w-4 text-success" />;
    case "video":
      return <FileVideo className="h-4 w-4 text-warning" />;
    case "unknown":
      return <Download className="h-4 w-4 text-muted-foreground" />;
    default:
      return <FileText className="h-4 w-4 text-muted-foreground" />;
  }
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
                {KIND_LABELS[
                  resolveRendererKind({
                    extension: attachment.extension,
                    mimeType: attachment.mimeType,
                    filename: attachment.displayName,
                  })
                ] ?? "Raw"}{" "}
                · {formatAttachmentSize(attachment.sizeBytes)}
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
