import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThinkingWordTicker } from "./ThinkingWordTicker";

describe("ThinkingWordTicker", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("types, holds, deletes, and restarts the active easter egg word", async () => {
    vi.useFakeTimers();

    render(
      <ThinkingWordTicker
        deletingDelayMs={5}
        holdDelayMs={30}
        switchDelayMs={10}
        typingDelayMs={10}
        words={["Go"]}
      />,
    );

    const ticker = screen.getByTestId("thinking-word-ticker-text");

    expect(ticker).toBeEmptyDOMElement();
    expect(screen.getByTestId("thinking-word-ticker-cursor")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(10);
    expect(ticker).toHaveTextContent("G");

    await vi.advanceTimersByTimeAsync(10);
    expect(ticker).toHaveTextContent("Go");

    await vi.advanceTimersByTimeAsync(30);
    expect(ticker).toHaveTextContent("Go");

    await vi.advanceTimersByTimeAsync(5);
    expect(ticker).toHaveTextContent("G");

    await vi.advanceTimersByTimeAsync(5);
    expect(ticker).toHaveTextContent("");

    await vi.advanceTimersByTimeAsync(20);
    expect(ticker).toHaveTextContent("G");
  });

  it("keeps a stable placeholder width based on the longest candidate word", () => {
    render(<ThinkingWordTicker words={["Go", "Longer"]} />);

    expect(screen.getByTestId("thinking-word-ticker-placeholder")).toHaveTextContent(
      "Longer",
    );
  });
});
