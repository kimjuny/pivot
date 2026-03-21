import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ConfigFieldGroup, { type ConfigFieldDefinition } from "./ConfigFieldGroup";

function buildField(key: string): ConfigFieldDefinition {
  return {
    key,
    label: key,
    type: "text",
    required: false,
  };
}

describe("ConfigFieldGroup", () => {
  it("keeps a single field group full-width instead of reserving an empty second column", () => {
    const { container } = render(
      <ConfigFieldGroup
        title="Credentials"
        description="Provider secrets"
        fields={[buildField("api_key")]}
        values={{ api_key: "" }}
        onChange={vi.fn()}
      />,
    );

    const grid = container.querySelector(".grid");
    expect(grid).not.toBeNull();
    expect(grid?.className).not.toContain("md:grid-cols-2");
    expect(screen.getByLabelText("api_key")).toBeInTheDocument();
  });

  it("keeps two-column layout for multi-field groups", () => {
    const { container } = render(
      <ConfigFieldGroup
        title="Credentials"
        description="Provider secrets"
        fields={[buildField("api_key"), buildField("base_url")]}
        values={{ api_key: "", base_url: "" }}
        onChange={vi.fn()}
      />,
    );

    const grid = container.querySelector(".grid");
    expect(grid).not.toBeNull();
    expect(grid?.className).toContain("md:grid-cols-2");
  });
});
