import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";

describe("CenteredLoadingIndicator", () => {
  it("renders a simple spinning loader immediately", () => {
    render(<CenteredLoadingIndicator label="Loading agents" />);

    expect(screen.getByText("Loading agents")).toHaveClass("sr-only");
    expect(screen.getByTestId("centered-loading-spinner")).toBeInTheDocument();
    expect(screen.getByTestId("centered-loading-spinner")).toHaveClass(
      "animate-spin",
    );
  });
});
