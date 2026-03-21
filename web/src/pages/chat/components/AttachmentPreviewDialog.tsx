import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { Loader2 } from "@/lib/lucide";

import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from "@/components/ui/dialog";
import { fetchChatFileBlob } from "@/utils/api";

import type { ChatAttachment } from "../types";

interface AttachmentPreviewDialogProps {
  attachment: ChatAttachment | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Opens one chat image in a focused dialog so thumbnail clicks share the same preview experience.
 */
export function AttachmentPreviewDialog({
  attachment,
  open,
  onOpenChange,
}: AttachmentPreviewDialogProps) {
  const [src, setSrc] = useState<string | null>(attachment?.previewUrl ?? null);
  const [hasLoadError, setHasLoadError] = useState<boolean>(false);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(
    null,
  );
  const shouldRenderImage =
    attachment !== null &&
    (attachment.kind === "image" || attachment.mimeType.startsWith("image/"));

  useEffect(() => {
    if (!open || !attachment || !shouldRenderImage) {
      setSrc(attachment?.previewUrl ?? null);
      setHasLoadError(false);
      setNaturalSize(null);
      return;
    }

    if (attachment.previewUrl) {
      setSrc(attachment.previewUrl);
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
        const blob = await fetchChatFileBlob(attachment.fileId, controller.signal);
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
  }, [attachment, open, shouldRenderImage]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay className="z-[2147483646]" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-[2147483647] -translate-x-1/2 -translate-y-1/2 outline-none">
          <DialogHeader className="sr-only">
            <DialogTitle>Full-size attachment preview</DialogTitle>
            <DialogDescription>
              Displays the selected chat image at a larger size.
            </DialogDescription>
          </DialogHeader>

          <div className="flex max-h-[96vh] max-w-[96vw] items-center justify-center overflow-auto">
            {!shouldRenderImage ? null : src ? (
              <img
                src={src}
                alt={attachment.originalName}
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
            ) : hasLoadError ? (
              <div className="rounded-lg bg-background/95 px-6 py-4 text-center text-sm text-muted-foreground shadow-2xl">
                Unable to load this image preview.
              </div>
            ) : (
              <div className="rounded-lg bg-background/95 p-4 shadow-2xl">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
}
