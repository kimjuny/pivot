import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownRenderer } from "./MarkdownRenderer";

describe("MarkdownRenderer", () => {
  it("keeps blockquote body text readable in document markdown", () => {
    render(
      <MarkdownRenderer
        variant="document"
        content={[
          "> **调研时间范围**：2026年1月1日 — 2026年4月1日  ",
          "> **报告生成日期**：2026年4月",
        ].join("\n")}
      />,
    );

    const blockquote = screen.getByText(/调研时间范围/).closest("blockquote");

    expect(blockquote).not.toBeNull();
    expect(blockquote).toHaveClass("text-foreground/85");
    expect(blockquote).toHaveTextContent(/调研时间范围：2026年1月1日 — 2026年4月1日/);
    expect(blockquote).toHaveTextContent(/报告生成日期：2026年4月/);
  });

  it("renders GFM tables as semantic table elements", () => {
    render(
      <MarkdownRenderer
        content={[
          "| Trend | Keyword |",
          "| --- | --- |",
          "| Architecture | DeepSeek mHC |",
        ].join("\n")}
      />,
    );

    const table = screen.getByRole("table");

    expect(table).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Trend" })).toBeInTheDocument();
    expect(
      screen.getByRole("cell", { name: "DeepSeek mHC" }),
    ).toBeInTheDocument();
  });

  it("renders fenced code blocks inside a dedicated block container", () => {
    render(
      <MarkdownRenderer
        content={"```ts\nconst answer = 42;\nconsole.log(answer);\n```"}
      />,
    );

    const codeBlock = screen.getByText(/const answer = 42;/);
    const pre = codeBlock.closest("pre");

    expect(pre).not.toBeNull();
    expect(pre).toHaveClass("max-w-full", "overflow-x-auto", "px-4", "py-3");
    expect(pre?.parentElement).toHaveClass(
      "not-prose",
      "rounded-xl",
      "border",
      "bg-muted",
    );
    expect(codeBlock).toHaveClass(
      "block",
      "bg-transparent",
      "font-mono",
      "whitespace-pre",
      "language-ts",
    );
  });

  it("keeps inline code rendered as a regular code span", () => {
    render(<MarkdownRenderer content={"Use `npm run test` before merging."} />);

    const inlineCode = screen.getByText("npm run test");

    expect(inlineCode.tagName).toBe("CODE");
    expect(inlineCode.closest("pre")).toBeNull();
    expect(inlineCode).not.toHaveClass("block", "whitespace-pre");
  });
});
