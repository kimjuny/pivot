import { describe, expect, it } from "vitest";

import { StreamingFieldExtractor } from "./streamingFieldExtractor";

function concat(deltas: { fieldName: string; delta: string }[], field: string): string {
  return deltas
    .filter((d) => d.fieldName === field)
    .map((d) => d.delta)
    .join("");
}

describe("StreamingFieldExtractor", () => {
  it("extracts a single field fed in one chunk", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const deltas = ex.feed('{"content":"hello"}');
    expect(concat(deltas, "content")).toBe("hello");
  });

  it("extracts incrementally across many chunks (write_file streaming)", () => {
    const ex = new StreamingFieldExtractor(["path", "content"]);
    const fragments = [
      '{"path":"inde',
      'x.html","conte',
      'nt":"<htm',
      'l>\\n<body>',
      '\\nhello\\n',
      '</body>\\n</html>"}',
    ];
    let all = "";
    for (const frag of fragments) {
      for (const d of ex.feed(frag)) {
        if (d.fieldName === "content") {
          all += d.delta;
        }
      }
    }
    expect(all).toBe("<html>\n<body>\nhello\n</body>\n</html>");
  });

  it("decodes JSON escapes on the fly", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const deltas = ex.feed('{"content":"a\\"b\\\\c\\nd\\u00e9"}');
    expect(concat(deltas, "content")).toBe('a"b\\c\ndé');
  });

  it("handles an escape sequence split across two chunks", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const all = [...ex.feed('{"content":"foo\\'), ...ex.feed('nbar"}')];
    expect(concat(all, "content")).toBe("foo\nbar");
  });

  it("handles a unicode escape split across chunks", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const all = [...ex.feed('{"content":"x\\u00'), ...ex.feed('e9"}')];
    expect(concat(all, "content")).toBe("xé");
  });

  it("skips unknown fields", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const deltas = ex.feed('{"path":"x","content":"y","flag":true}');
    expect(concat(deltas, "content")).toBe("y");
  });

  it("does not treat a known field name used as a value as a field", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const deltas = ex.feed('{"label":"content","content":"real"}');
    expect(concat(deltas, "content")).toBe("real");
  });

  it("does not re-enter a completed field", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    ex.feed('{"content":"a"}');
    const deltas = ex.feed(',"more":"content"');
    expect(concat(deltas, "content")).toBe("");
  });

  it("extracts multiple known fields from one stream", () => {
    const ex = new StreamingFieldExtractor(["old_string", "new_string"]);
    const deltas = ex.feed(
      '{"path":"a.py","old_string":"foo","new_string":"bar"}',
    );
    expect(concat(deltas, "old_string")).toBe("foo");
    expect(concat(deltas, "new_string")).toBe("bar");
  });

  it("markComplete flushes a field cut off mid-stream", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    ex.feed('{"content":"unfinis');
    const deltas = ex.markComplete();
    expect(deltas).toEqual([
      { fieldName: "content", delta: "", isFinal: true },
    ]);
  });

  it("emits isFinal=true once when a field's closing quote arrives", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const first = ex.feed('{"content":"hel');
    const second = ex.feed('lo"}');
    expect(first.some((d) => d.isFinal)).toBe(false);
    const finals = second.filter((d) => d.isFinal);
    expect(finals).toHaveLength(1);
    expect(finals[0].fieldName).toBe("content");
  });

  it("feeds a large single chunk efficiently", () => {
    const ex = new StreamingFieldExtractor(["content"]);
    const big = "x".repeat(5000);
    const deltas = ex.feed(`{"content":"${big}"}`);
    expect(concat(deltas, "content")).toBe(big);
  });
});
