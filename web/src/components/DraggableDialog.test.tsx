import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import DraggableDialog from "./DraggableDialog";

function getDialogShell() {
  return screen.getByText("Dialog body").closest(".fixed");
}

describe("DraggableDialog", () => {
  it("hides the fullscreen control unless the dialog opts into it", () => {
    render(
      <DraggableDialog
        open
        onOpenChange={vi.fn()}
        title="Dialog title"
      >
        <div>Dialog body</div>
      </DraggableDialog>,
    );

    expect(
      screen.queryByRole("button", { name: "Enter fullscreen" }),
    ).not.toBeInTheDocument();
  });

  it("toggles between windowed and fullscreen layouts when enabled", async () => {
    const user = userEvent.setup();
    const expectedWidth = `${window.innerWidth * 0.75}px`;
    const expectedHeight = `${window.innerHeight * 0.75}px`;
    const expectedFullscreenWidth = `${window.innerWidth}px`;
    const expectedFullscreenHeight = `${window.innerHeight}px`;

    render(
      <DraggableDialog
        open
        onOpenChange={vi.fn()}
        title="Dialog title"
        size="large"
        fullscreenable
      >
        <div>Dialog body</div>
      </DraggableDialog>,
    );

    const dialogShell = getDialogShell();
    expect(dialogShell).not.toBeNull();
    expect(dialogShell).toHaveStyle({
      width: expectedWidth,
      height: expectedHeight,
    });

    await user.click(
      screen.getByRole("button", { name: "Enter fullscreen" }),
    );

    expect(
      screen.getByRole("button", { name: "Exit fullscreen" }),
    ).toBeInTheDocument();
    expect(dialogShell).toHaveStyle({
      width: expectedFullscreenWidth,
      height: expectedFullscreenHeight,
    });

    await user.click(
      screen.getByRole("button", { name: "Exit fullscreen" }),
    );

    expect(
      screen.getByRole("button", { name: "Enter fullscreen" }),
    ).toBeInTheDocument();
    expect(dialogShell).toHaveStyle({
      width: expectedWidth,
      height: expectedHeight,
    });
  });
});
