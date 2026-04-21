import { Badge } from "@/components/ui/badge";
import {
  formatProviderStatusLabel,
  formatProviderVisibilityLabel,
} from "@/utils/providerMetadata";

interface ProviderMetadataBadgesProps {
  visibility: string;
  status: string;
  mediaType?: "image" | "video" | null;
}

/**
 * Render compact badges that explain provider origin and availability.
 */
export function ProviderMetadataBadges({
  visibility,
  status,
  mediaType = null,
}: ProviderMetadataBadgesProps) {
  const visibilityLabel = formatProviderVisibilityLabel(visibility);
  const statusLabel = formatProviderStatusLabel(status);
  const mediaTypeLabel =
    mediaType === "image" ? "Image" : mediaType === "video" ? "Video" : null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {mediaTypeLabel ? (
        <Badge variant="secondary" className="text-[11px]">
          {mediaTypeLabel}
        </Badge>
      ) : null}
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
