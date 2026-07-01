import { useState } from "react";
import { AlertCircle } from "lucide-react";

interface VideoRendererProps {
  /** Object URL for the raw video blob (owned by the parent dialog). */
  objectUrl: string;
  displayName: string;
  mimeType: string;
}

/**
 * Native `<video>` player. The browser decodes only a subset of containers
 * (mp4/webm/ogg reliably; mov/avi/mkv often not), so an `onError` fallback
 * points the user to the download action instead of leaving a blank box.
 */
export function VideoRenderer({
  objectUrl,
  displayName,
  mimeType,
}: VideoRendererProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border/70 bg-muted/20 px-6 text-center">
        <AlertCircle className="h-8 w-8 text-warning" />
        <div className="space-y-1">
          <p className="text-sm font-medium text-foreground">
            This video format can't play in the browser
          </p>
          <p className="text-xs text-muted-foreground">
            {displayName} ({mimeType || "unknown format"}) isn't supported for
            inline playback. Use the download action in the title bar to open it
            locally.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center bg-black">
      <video
        key={objectUrl}
        src={objectUrl}
        controls
        className="max-h-full max-w-full"
        onError={() => setFailed(true)}
      >
        Your browser does not support video playback.
      </video>
    </div>
  );
}
