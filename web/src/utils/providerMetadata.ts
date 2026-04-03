/**
 * Normalize backend provider visibility labels into short user-facing text.
 */
export function formatProviderVisibilityLabel(visibility: string): string {
  if (visibility === "extension") {
    return "Extension";
  }
  return "Built-in";
}

/**
 * Normalize backend provider status labels into short user-facing text.
 */
export function formatProviderStatusLabel(status: string): string {
  if (status === "active") {
    return "Active";
  }
  if (status === "disabled") {
    return "Disabled";
  }
  return status;
}

/**
 * Render a concise extension package reference for one provider manifest.
 */
export function formatProviderExtensionLabel(
  extensionDisplayName?: string | null,
  extensionName?: string | null,
  extensionVersion?: string | null,
): string | null {
  const name = extensionDisplayName || extensionName;
  if (!name) {
    return null;
  }
  if (extensionVersion) {
    return `${name}@${extensionVersion}`;
  }
  return name;
}
