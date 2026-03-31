import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownRenderer } from "./MarkdownRenderer";

describe("MarkdownRenderer", () => {
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
