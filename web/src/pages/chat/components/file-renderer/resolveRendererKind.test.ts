import { describe, expect, it } from "vitest";

import { resolveRendererKind } from "./resolveRendererKind";

const kind = (extension: string, mimeType: string, filename?: string) =>
  resolveRendererKind({ extension, mimeType, filename });

describe("resolveRendererKind", () => {
  it("routes pdf by extension or mime", () => {
    expect(kind("pdf", "application/pdf")).toBe("pdf");
    expect(kind("", "application/pdf")).toBe("pdf");
  });

  it("routes docx by extension or openxml mime keyword", () => {
    expect(kind("docx", "application/octet-stream")).toBe("docx");
    expect(
      kind(
        "",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ),
    ).toBe("docx");
  });

  it("routes xlsx, xls and csv to the shared spreadsheet renderer", () => {
    expect(kind("xlsx", "application/octet-stream")).toBe("spreadsheet");
    expect(kind("xls", "application/octet-stream")).toBe("spreadsheet");
    expect(kind("csv", "text/csv")).toBe("spreadsheet");
    expect(
      kind("", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ).toBe("spreadsheet");
  });

  it("does NOT let csv fall through to text (regression guard)", () => {
    expect(kind("csv", "text/csv")).not.toBe("text");
    expect(kind("csv", "application/octet-stream")).not.toBe("text");
  });

  it("routes any video/* mime to video, including matroska", () => {
    expect(kind("mp4", "video/mp4")).toBe("video");
    expect(kind("webm", "video/webm")).toBe("video");
    expect(kind("mkv", "video/x-matroska")).toBe("video");
  });

  it("routes image/* mime to image", () => {
    expect(kind("png", "image/png")).toBe("image");
    expect(kind("", "image/svg+xml")).toBe("image");
  });

  it("routes markdown by extension or mime", () => {
    expect(kind("md", "text/markdown")).toBe("markdown");
    expect(kind("markdown", "text/plain")).toBe("markdown");
    expect(kind("", "text/x-markdown")).toBe("markdown");
  });

  it("routes code/text extensions to text", () => {
    expect(kind("py", "text/x-python")).toBe("text");
    expect(kind("ts", "text/plain")).toBe("text");
    expect(kind("json", "application/json")).toBe("text");
    expect(kind("txt", "text/plain")).toBe("text");
  });

  it("routes extensionless text filenames like dockerfile via filename", () => {
    expect(kind("", "application/octet-stream", "dockerfile")).toBe("text");
    expect(kind("", "application/octet-stream", "Makefile")).toBe("text");
  });

  it("is case-insensitive on extension, mime and filename", () => {
    expect(kind("PDF", "APPLICATION/PDF")).toBe("pdf");
    expect(kind("XLSX", "APPLICATION/OCTET-STREAM")).toBe("spreadsheet");
    expect(kind("MD", "TEXT/PLAIN")).toBe("markdown");
  });

  it("falls back to unknown for unsupported binary formats", () => {
    expect(kind("pptx", "application/octet-stream")).toBe("unknown");
    expect(kind("doc", "application/msword")).toBe("unknown");
    expect(kind("zip", "application/zip")).toBe("unknown");
    expect(kind("exe", "application/octet-stream")).toBe("unknown");
  });
});
