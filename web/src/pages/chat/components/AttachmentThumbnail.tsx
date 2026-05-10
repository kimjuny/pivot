import { useEffect, useState } from "react";
import {
  FileSpreadsheet,
  FileText,
  Loader2,
  Presentation,
} from "lucide-react";

import { fetchChatFileBlob } from "@/utils/api";

import type { ChatAttachment } from "../types";

interface AttachmentFileIconProps {
  attachment: ChatAttachment;
}

/**
 * Renders a deterministic icon for non-image attachments so document previews stay recognizable.
 */
function AttachmentFileIcon({ attachment }: AttachmentFileIconProps) {
  const extension = attachment.extension.toLowerCase();
  if (extension === "pptx") {
    return <Presentation className="h-5 w-5 text-muted-foreground" />;
  }

  if (extension === "xlsx") {
    return <FileSpreadsheet className="h-5 w-5 text-muted-foreground" />;
  }

  return <FileText className="h-5 w-5 text-muted-foreground" />;
}

interface AttachmentThumbnailProps {
  attachment: ChatAttachment;
  alt: string;
  className?: string;
}

/**
 * Resolves authenticated image thumbnails on demand while falling back to document icons.
 */
export function AttachmentThumbnail({
  attachment,
  alt,
  className,
}: AttachmentThumbnailProps) {
  const [src, setSrc] = useState<string | null>(attachment.previewUrl ?? null);
  const shouldRenderImage =
    attachment.kind === "image" || attachment.mimeType.startsWith("image/");

  useEffect(() => {
    if (!shouldRenderImage) {
      setSrc(null);
      return;
    }

    if (attachment.previewUrl) {
      setSrc(attachment.previewUrl);
      return;
    }

    const controller = new AbortController();
    let objectUrl: string | null = null;

    const loadImage = async () => {
      try {
        const blob = await fetchChatFileBlob(attachment.fileId, controller.signal);
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        console.error("Failed to load image attachment:", error);
      }
    };

    void loadImage();

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [attachment.fileId, attachment.previewUrl, shouldRenderImage]);

  if (!shouldRenderImage) {
    return (
      <div
        className={`flex h-full w-full items-start justify-center bg-muted pt-1.5 ${className ?? ""}`}
      >
        <AttachmentFileIcon attachment={attachment} />
      </div>
    );
  }

  if (src) {
    return (
      <img
        src={src}
        alt={alt}
        className={className ?? "h-full w-full object-cover"}
      />
    );
  }

  return (
    <div
      className={`flex h-full w-full items-center justify-center bg-muted ${className ?? ""}`}
    >
      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
    </div>
  );
}
