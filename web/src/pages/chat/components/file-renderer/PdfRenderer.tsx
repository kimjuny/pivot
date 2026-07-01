import { useCallback, useEffect, useState } from "react";
import { Document, Page } from "react-pdf";

import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import { RendererError, RendererLoading } from "./renderer-states";

interface PdfRendererProps {
  /** Raw PDF blob. Read into an ArrayBuffer for react-pdf's <Document>. */
  blob: Blob;
}

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;
const SCALE_STEP = 0.2;

const iconButtonClass =
  "inline-flex h-6 w-6 items-center justify-center rounded p-1 text-foreground transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-40";

/**
 * Single-page-at-a-time PDF viewer with a compact toolbar (prev/next + zoom).
 * The draggable dialog has limited height, so we render one page centered in a
 * scrolling region rather than a continuous strip.
 */
export default function PdfRenderer({ blob }: PdfRendererProps) {
  const [data, setData] = useState<ArrayBuffer | null>(null);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setNumPages(null);
    setLoadError(null);
    setPageNumber(1);

    blob
      .arrayBuffer()
      .then((buffer) => {
        if (!cancelled) {
          setData(buffer);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(
            err instanceof Error ? err.message : "Failed to read this PDF.",
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [blob]);

  const handleLoadSuccess = useCallback(({ numPages: total }: { numPages: number }) => {
    setNumPages(total);
    setPageNumber(1);
  }, []);

  const handleLoadError = useCallback((err: Error) => {
    setLoadError(err?.message ?? "Failed to load this PDF.");
  }, []);

  const goPrev = () => setPageNumber((p) => Math.max(1, p - 1));
  const goNext = () => setPageNumber((p) => Math.min(numPages ?? 1, p + 1));
  const zoomOut = () =>
    setScale((s) => Math.max(MIN_SCALE, Number((s - SCALE_STEP).toFixed(2))));
  const zoomIn = () =>
    setScale((s) => Math.min(MAX_SCALE, Number((s + SCALE_STEP).toFixed(2))));

  if (loadError) {
    return <RendererError message={loadError} />;
  }

  return (
    <div className="flex h-full flex-col bg-muted/20">
      <div className="flex shrink-0 items-center justify-center gap-1.5 border-b border-border bg-background px-3 py-1.5">
        <button
          type="button"
          onClick={goPrev}
          disabled={pageNumber <= 1}
          className={iconButtonClass}
          aria-label="Previous page"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="min-w-[60px] text-center text-xs tabular-nums text-muted-foreground">
          {numPages ? `${pageNumber} / ${numPages}` : "—"}
        </span>
        <button
          type="button"
          onClick={goNext}
          disabled={!numPages || pageNumber >= numPages}
          className={iconButtonClass}
          aria-label="Next page"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
        <div className="mx-1.5 h-4 w-px bg-border" />
        <button
          type="button"
          onClick={zoomOut}
          disabled={scale <= MIN_SCALE}
          className={iconButtonClass}
          aria-label="Zoom out"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <span className="min-w-[44px] text-center text-xs tabular-nums text-muted-foreground">
          {Math.round(scale * 100)}%
        </span>
        <button
          type="button"
          onClick={zoomIn}
          disabled={scale >= MAX_SCALE}
          className={iconButtonClass}
          aria-label="Zoom in"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="flex justify-center p-4">
          <Document
            file={data ?? undefined}
            onLoadSuccess={handleLoadSuccess}
            onLoadError={handleLoadError}
            loading={<RendererLoading />}
          >
            <Page
              pageNumber={pageNumber}
              scale={scale}
              renderTextLayer
              renderAnnotationLayer
              className="rounded-lg border border-border/70 shadow-sm"
            />
          </Document>
        </div>
      </div>
    </div>
  );
}
