import { type ReactNode, useEffect, useState } from "react";

interface ExtensionLogoAvatarProps {
  name: string;
  logoUrl?: string | null;
  fallback: ReactNode;
  containerClassName: string;
  imageClassName: string;
}

/**
 * Renders one extension logo when the package ships a logo asset, then falls
 * back to the caller-provided glyph if the asset is missing or fails to load.
 */
export function ExtensionLogoAvatar({
  name,
  logoUrl = null,
  fallback,
  containerClassName,
  imageClassName,
}: ExtensionLogoAvatarProps) {
  const [hasImageError, setHasImageError] = useState(false);

  useEffect(() => {
    // Reset transient image failures when the backing package changes so list
    // refreshes can recover after an extension adds a valid logo asset.
    setHasImageError(false);
  }, [logoUrl]);

  return (
    <div className={containerClassName}>
      {logoUrl && !hasImageError ? (
        <img
          src={logoUrl}
          alt={`${name} logo`}
          className={imageClassName}
          loading="lazy"
          onError={() => {
            setHasImageError(true);
          }}
        />
      ) : (
        fallback
      )}
    </div>
  );
}
