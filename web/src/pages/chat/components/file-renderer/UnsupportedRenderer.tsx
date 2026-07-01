import { FileQuestion } from "lucide-react";

interface UnsupportedRendererProps {
  /** File name shown in the "download the raw file" hint, when available. */
  displayName?: string;
}

/**
 * Placeholder shown when no inline renderer matches the attachment. The dialog
 * header still offers a download action, so this only needs to explain why the
 * body is empty and nudge the user toward it.
 */
export function UnsupportedRenderer({ displayName }: UnsupportedRendererProps) {
  return (
    <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border/70 bg-muted/20 px-6 text-center">
      <FileQuestion className="h-8 w-8 text-muted-foreground" />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">
          Unsupported file type
        </p>
        <p className="text-xs text-muted-foreground">
          {displayName
            ? `${displayName} cannot be previewed inline.`
            : "This attachment cannot be previewed inline."}
          {" "}
          Use the download action in the title bar to open the raw file.
        </p>
      </div>
    </div>
  );
}
