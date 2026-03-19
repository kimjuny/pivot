import { type ReactNode, useEffect, useState } from "react";

import { getLLMBrandIconCandidates } from "../utils/llmBrandIcon";

interface LLMBrandAvatarProps {
  model: string | null | undefined;
  fallback: ReactNode;
  containerClassName: string;
  imageClassName: string;
}

/**
 * Renders one model avatar by probing likely icon files derived from the model
 * name before falling back to a generic glyph.
 */
export function LLMBrandAvatar({
  model,
  fallback,
  containerClassName,
  imageClassName,
}: LLMBrandAvatarProps) {
  const iconCandidates = getLLMBrandIconCandidates(model);
  const [candidateIndex, setCandidateIndex] = useState(0);

  useEffect(() => {
    // Reset probing whenever the backing model changes so list rows do not keep
    // stale failure state after filters, edits, or pagination updates.
    setCandidateIndex(0);
  }, [model]);

  const iconPath = iconCandidates[candidateIndex] ?? null;

  return (
    <div className={containerClassName}>
      {iconPath ? (
        <img
          src={iconPath}
          alt=""
          className={imageClassName}
          loading="lazy"
          aria-hidden="true"
          onError={() => {
            setCandidateIndex((currentIndex) => currentIndex + 1);
          }}
        />
      ) : (
        fallback
      )}
    </div>
  );
}
