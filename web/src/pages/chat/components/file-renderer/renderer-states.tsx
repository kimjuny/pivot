import { AlertCircle, Loader2 } from "lucide-react";

/** Centered spinner shown while a renderer parses its blob. */
export function RendererLoading() {
  return (
    <div className="flex h-full min-h-40 items-center justify-center text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin" />
    </div>
  );
}

/** Inline error block for renderer parse/load failures. */
export function RendererError({ message }: { message: string }) {
  return (
    <div className="m-4 rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
      {message}
    </div>
  );
}

/** Empty-state block for sheets / documents with no renderable rows. */
export function RendererEmpty({ message }: { message: string }) {
  return (
    <div className="flex h-full min-h-40 items-center justify-center text-sm text-muted-foreground">
      <AlertCircle className="mr-2 h-4 w-4" />
      {message}
    </div>
  );
}
