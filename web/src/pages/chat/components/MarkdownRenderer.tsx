import ReactMarkdown from "react-markdown";

interface MarkdownRendererProps {
  content: string;
  variant?: "chat" | "document";
}

const BASE_MARKDOWN_CLASSES =
  "prose max-w-none text-foreground " +
  "prose-headings:scroll-m-20 prose-headings:font-semibold prose-headings:text-foreground " +
  "prose-p:text-foreground/90 prose-p:leading-7 " +
  "prose-strong:font-semibold prose-strong:text-foreground " +
  "prose-a:text-primary prose-a:no-underline hover:prose-a:underline " +
  "prose-ul:pl-6 prose-ol:pl-6 " +
  "prose-li:leading-7 prose-li:text-foreground/90 " +
  "prose-hr:border-border/70 " +
  "prose-blockquote:border-l-primary prose-blockquote:text-foreground/80 " +
  "prose-code:rounded prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:text-[0.85em] prose-code:font-medium prose-code:text-foreground " +
  "prose-pre:rounded-xl prose-pre:border prose-pre:border-border/70 prose-pre:bg-muted/40 prose-pre:text-foreground " +
  "prose-table:w-full prose-table:table-fixed prose-th:border prose-th:border-border/70 prose-th:bg-muted/35 prose-th:px-3 prose-th:py-2 prose-th:text-left prose-th:text-foreground " +
  "prose-td:border prose-td:border-border/60 prose-td:px-3 prose-td:py-2 prose-td:align-top";

const CHAT_MARKDOWN_CLASSES =
  "prose-sm " +
  "prose-headings:mb-2 prose-headings:mt-5 " +
  "prose-h1:text-2xl prose-h1:tracking-tight " +
  "prose-h2:text-xl prose-h2:border-b prose-h2:border-border/60 prose-h2:pb-1.5 " +
  "prose-h3:text-lg prose-h4:text-base " +
  "prose-p:my-2.5 prose-ul:my-3 prose-ol:my-3 prose-hr:my-6";

const DOCUMENT_MARKDOWN_CLASSES =
  "prose-sm sm:prose-base " +
  "prose-headings:mb-3 prose-headings:mt-6 " +
  "prose-h1:mb-4 prose-h1:text-3xl prose-h1:tracking-tight " +
  "prose-h2:mt-8 prose-h2:border-b prose-h2:border-border/60 prose-h2:pb-2 prose-h2:text-2xl " +
  "prose-h3:mt-6 prose-h3:text-xl prose-h4:mt-5 prose-h4:text-lg " +
  "prose-p:my-3 prose-ul:my-4 prose-ol:my-4 prose-hr:my-8";

/**
 * Renders model-authored markdown with the same parser and typography across chat surfaces.
 */
export function MarkdownRenderer({
  content,
  variant = "chat",
}: MarkdownRendererProps) {
  if (!content.trim()) {
    return null;
  }

  const variantClasses =
    variant === "document" ? DOCUMENT_MARKDOWN_CLASSES : CHAT_MARKDOWN_CLASSES;

  return (
    <article className={`${BASE_MARKDOWN_CLASSES} ${variantClasses}`}>
      <ReactMarkdown>{content}</ReactMarkdown>
    </article>
  );
}
