import { icons } from "lucide-react";
import type { LucideIcon } from "lucide-react";

function kebabToPascal(str: string): string {
  return str
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join("");
}

const cache = new Map<string, LucideIcon | null>();

/**
 * Resolve a kebab-case icon name (e.g. "layout-dashboard") to a Lucide
 * component. Used by extension surface manifests where the icon name is
 * declared at runtime and cannot be statically imported.
 */
export function resolveIcon(
  name: string | null | undefined,
): LucideIcon | null {
  if (!name) return null;
  const cached = cache.get(name);
  if (cached !== undefined) return cached;
  const result = (icons as Record<string, LucideIcon>)[kebabToPascal(name)] ?? null;
  cache.set(name, result);
  return result;
}
