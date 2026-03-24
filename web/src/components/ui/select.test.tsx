import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import DraggableDialog from "../DraggableDialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";

/**
 * Radix Select expects pointer-capture helpers that happy-dom does not ship.
 */
function applyPointerCapturePolyfill() {
  if (!("hasPointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "hasPointerCapture", {
      value: () => false,
      configurable: true,
    });
  }
  if (!("setPointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "setPointerCapture", {
      value: () => {},
      configurable: true,
    });
  }
  if (!("releasePointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "releasePointerCapture", {
      value: () => {},
      configurable: true,
    });
  }
}

describe("Select", () => {
  beforeEach(() => {
    applyPointerCapturePolyfill();
  });

  it("renders dropdown content above draggable dialogs", async () => {
    const user = userEvent.setup();

    render(
      <DraggableDialog open onOpenChange={() => {}} title="Dialog title">
        <label htmlFor="dialog-select">Type</label>
        <Select>
          <SelectTrigger id="dialog-select">
            <SelectValue placeholder="Select type…" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="normal">Normal</SelectItem>
          </SelectContent>
        </Select>
      </DraggableDialog>,
    );

    await user.click(screen.getByRole("combobox", { name: "Type" }));

    const selectContent = await screen.findByRole("listbox");
    expect(selectContent).toHaveClass("!z-[9999]");
  });
});
