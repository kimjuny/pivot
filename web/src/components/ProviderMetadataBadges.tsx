import { Badge } from "@/components/ui/badge";
import {
  formatProviderStatusLabel,
  formatProviderVisibilityLabel,
} from "@/utils/providerMetadata";

interface ProviderMetadataBadgesProps {
  visibility: string;
  status: string;
}

/**
 * Render compact badges that explain provider origin and availability.
 */
export function ProviderMetadataBadges({
  visibility,
  status,
}: ProviderMetadataBadgesProps) {
  const visibilityLabel = formatProviderVisibilityLabel(visibility);
  const statusLabel = formatProviderStatusLabel(status);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline" className="text-[11px]">
        {visibilityLabel}
      </Badge>
      <Badge
        variant={status === "active" ? "secondary" : "outline"}
        className="text-[11px]"
      >
        {statusLabel}
      </Badge>
    </div>
  );
}
