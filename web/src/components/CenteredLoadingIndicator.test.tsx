import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";

describe("CenteredLoadingIndicator", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits before showing the Motion loading animation", async () => {
    vi.useFakeTimers();

    render(<CenteredLoadingIndicator label="Loading agents" />);

    expect(screen.getByText("Loading agents")).toHaveClass("sr-only");
    expect(
      screen.queryByTestId("reorder-loading-animation"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("reorder-loading-placeholder"),
    ).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });

    expect(
      screen.queryByTestId("reorder-loading-animation"),
    ).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(
      screen.getByTestId("reorder-loading-animation"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("reorder-loading-placeholder"),
    ).not.toBeInTheDocument();
  });
});
