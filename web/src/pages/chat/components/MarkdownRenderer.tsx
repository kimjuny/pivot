import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

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

const BLOCK_CODE_WRAPPER_CLASSES =
  "not-prose my-4 overflow-hidden rounded-xl border border-border/60 bg-muted";

const BLOCK_PRE_CLASSES =
  "m-0 max-w-full overflow-x-auto px-4 py-3 text-sm leading-6";

const BLOCK_CODE_CLASSES =
  "block min-w-full bg-transparent p-0 font-mono text-[13px] font-medium text-foreground whitespace-pre";

type MarkdownPreProps = ComponentPropsWithoutRef<"pre">;
type MarkdownCodeProps = ComponentPropsWithoutRef<"code">;
type MarkdownBlockquoteProps = ComponentPropsWithoutRef<"blockquote">;

const MARKDOWN_COMPONENTS = {
  blockquote({
    className,
    children,
    ...props
  }: MarkdownBlockquoteProps) {
    return (
      <blockquote
        className={cn(
          "my-4 border-l-4 border-l-primary pl-4 text-foreground/85",
          "[&>p]:my-0 [&>p]:text-foreground/85 [&_strong]:font-semibold [&_strong]:text-foreground",
          className,
        )}
        {...props}
      >
        {children}
      </blockquote>
    );
  },
  pre({ className, children, ...props }: MarkdownPreProps) {
    return (
      <div className={BLOCK_CODE_WRAPPER_CLASSES}>
        <pre className={cn(BLOCK_PRE_CLASSES, className)} {...props}>
          {children}
        </pre>
      </div>
    );
  },
  code({ className, children, ...props }: MarkdownCodeProps) {
    const content = Array.isArray(children)
      ? children
          .filter((child): child is string => typeof child === "string")
          .join("")
      : typeof children === "string"
        ? children
        : "";
    const isBlockCode =
      (className?.includes("language-") ?? false) ||
      (content?.includes("\n") ?? false);

    if (!isBlockCode) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }

    return (
      <code className={cn(BLOCK_CODE_CLASSES, className)} {...props}>
        {children}
      </code>
    );
  },
};

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
      <ReactMarkdown
        components={MARKDOWN_COMPONENTS}
        remarkPlugins={[remarkGfm]}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}
