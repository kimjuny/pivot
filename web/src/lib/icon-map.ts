import type { SVGProps } from "react";
import type { ComponentType } from "react";

import {
  Code,
  LayoutDashboard,
} from "@/lib/lucide";

/**
 * Synchronous kebab-case -> component lookup for runtime-resolved icon names
 * (e.g. extension manifest `icon` fields).
 * Add new entries as extensions declare new lucide icon names.
 */
export const ICON_MAP: Record<
  string,
  ComponentType<SVGProps<SVGSVGElement>>
> = {
  "layout-dashboard": LayoutDashboard,
  "code": Code,
};
