import "./pdfWorker";

import { useMemo } from "react";
import Editor from "@monaco-editor/react";

import { MarkdownRenderer } from "../MarkdownRenderer";
import { getEditorLanguage, useResolvedMonacoTheme } from "./monaco";
import { RendererLoading } from "./renderer-states";
import { resolveRendererKind, type RendererKind } from "./resolveRendererKind";
import { UnsupportedRenderer } from "./UnsupportedRenderer";
import { VideoRenderer } from "./VideoRenderer";
import PdfRenderer from "./PdfRenderer";
import DocxRenderer from "./DocxRenderer";
import SpreadsheetRenderer from "./SpreadsheetRenderer";

// The renderers are imported eagerly rather than via React.lazy(). With this
// app's module graph, React.lazy() in Vite 4 dev reliably hangs in the Suspense
// fallback forever (the lazy payload's _init never runs), so the first open of
// any attachment spins indefinitely. Eager import removes that failure mode;
// the heavy deps (pdfjs/react-pdf) are already pulled in eagerly by pdfWorker,
// so the real incremental cost is only docx-preview + xlsx.

interface FileRendererProps {
  /** Fetched file blob. Required for every kind except image/video (objectUrl). */
  blob: Blob | null;
  /** Object URL for the blob. Required for image/video rendering. */
  objectUrl: string | null;
  displayName: string;
  extension: string;
  mimeType: string;
  /** Decoded text, supplied by the parent only for markdown/text kinds. */
  textContent?: string;
}

/**
 * Routes one attachment to the right renderer based purely on its extension
 * and MIME type (see {@link resolveRendererKind}). Shared by the assistant and
 * user attachment dialogs so there is a single source of truth for "how is
 * this file drawn".
 */
export function FileRenderer({
  blob,
  objectUrl,
  displayName,
  extension,
  mimeType,
  textContent,
}: FileRendererProps) {
  const kind = useMemo<RendererKind>(
    () =>
      resolveRendererKind({ extension, mimeType, filename: displayName }),
    [extension, mimeType, displayName],
  );
  const monacoTheme = useResolvedMonacoTheme();
  const content = textContent ?? "";

  switch (kind) {
    case "markdown":
      return (
        <div className="h-full overflow-auto">
          <div className="mx-auto w-full max-w-5xl px-4 py-4 md:px-8 lg:px-12">
            <MarkdownRenderer content={content} variant="document" />
          </div>
        </div>
      );

    case "text":
      return (
        <div className="h-full bg-muted/20">
          <Editor
            height="100%"
            language={getEditorLanguage(extension, displayName, mimeType)}
            value={content}
            theme={monacoTheme}
            loading={<RendererLoading />}
            options={{
              automaticLayout: true,
              domReadOnly: true,
              fontSize: 13,
              lineNumbers: "on",
              minimap: { enabled: false },
              readOnly: true,
              renderLineHighlight: "none",
              renderWhitespace: "selection",
              scrollBeyondLastLine: false,
              wordWrap: "on",
            }}
          />
        </div>
      );

    case "image":
      return objectUrl ? (
        <div className="flex h-full items-center justify-center overflow-auto p-4">
          <img
            src={objectUrl}
            alt={displayName}
            className="max-h-full max-w-full rounded-lg border border-border/70 bg-muted/20 object-contain"
          />
        </div>
      ) : null;

    case "video":
      return objectUrl ? (
        <VideoRenderer
          objectUrl={objectUrl}
          displayName={displayName}
          mimeType={mimeType}
        />
      ) : null;

    case "pdf":
      return blob ? <PdfRenderer blob={blob} /> : null;

    case "docx":
      return blob ? <DocxRenderer blob={blob} /> : null;

    case "spreadsheet":
      return blob ? <SpreadsheetRenderer blob={blob} /> : null;

    case "unknown":
    default:
      return <UnsupportedRenderer displayName={displayName} />;
  }
}
