import { useEffect, useRef, useState } from "react";
import { renderAsync } from "docx-preview";

import { RendererError, RendererLoading } from "./renderer-states";

interface DocxRendererProps {
  /** Raw .docx blob. docx-preview accepts a Blob directly. */
  blob: Blob;
}

/**
 * Renders a .docx into HTML that mirrors the Word layout as closely as the
 * library can. The document keeps its native white page on a neutral backdrop
 * (Google-Docs style) and is intentionally NOT inverted in dark mode —
 * docx-preview reproduces the authored colors, and inverting them would distort
 * the original.
 */
export default function DocxRenderer({ blob }: DocxRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    container.innerHTML = "";

    renderAsync(blob, container, undefined, {
      useBase64URL: true,
      inWrapper: true,
      breakPages: true,
      experimental: true,
    })
      .then(() => {
        if (cancelled) {
          return;
        }
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setError(
          err instanceof Error
            ? err.message
            : "Failed to render this document.",
        );
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [blob]);

  return (
    <div className="relative h-full overflow-auto bg-muted/30 p-4 md:p-8">
      <div ref={containerRef} className="flex justify-center [&_.docx-wrapper]:bg-transparent" />
      {loading ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/50">
          <RendererLoading />
        </div>
      ) : null}
      {error ? (
        <div className="absolute inset-0 flex items-center justify-center p-4">
          <RendererError message={error} />
        </div>
      ) : null}
    </div>
  );
}
