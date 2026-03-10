import type { JSX } from "react";

interface FormattedAnswerContentProps {
  content: string;
}

/**
 * Applies the lightweight markdown rules already supported by the existing chat answer UI.
 */
export function FormattedAnswerContent({
  content,
}: FormattedAnswerContentProps) {
  return <>{formatAnswerContent(content)}</>;
}

/**
 * Converts the backend's lightweight markdown output into timeline-friendly JSX blocks.
 */
function formatAnswerContent(content: string) {
  if (!content) {
    return null;
  }

  const lines = content.split("\n");
  const blocks: string[] = [];
  let currentBlock: string[] = [];

  for (const line of lines) {
    if (line.match(/^#{3,4}\s+/)) {
      if (currentBlock.length > 0) {
        blocks.push(currentBlock.join("\n"));
        currentBlock = [];
      }
      currentBlock.push(line);
    } else if (line.trim() === "" && currentBlock.length > 0) {
      currentBlock.push(line);
    } else {
      currentBlock.push(line);
    }
  }

  if (currentBlock.length > 0) {
    blocks.push(currentBlock.join("\n"));
  }

  return blocks
    .map((block, blockIndex) => {
      const trimmedBlock = block.trim();
      if (!trimmedBlock) {
        return null;
      }

      const h4Match = trimmedBlock.match(/^####\s+(.+?)(\n|$)/);
      const h3Match = trimmedBlock.match(/^###\s+(.+?)(\n|$)/);

      if (h4Match) {
        const headingText = h4Match[1];
        const remainingText = trimmedBlock.substring(h4Match[0].length).trim();

        return (
          <div key={blockIndex} className="mb-2.5">
            <h4 className="mb-1.5 text-sm font-semibold text-foreground">
              {headingText}
            </h4>
            {remainingText && (
              <div className="text-sm leading-relaxed text-foreground">
                {formatInlineMarkdown(remainingText)}
              </div>
            )}
          </div>
        );
      }

      if (h3Match) {
        const headingText = h3Match[1];
        const remainingText = trimmedBlock.substring(h3Match[0].length).trim();

        return (
          <div key={blockIndex} className="mb-3">
            <h3 className="mb-2 text-base font-bold text-foreground">
              {headingText}
            </h3>
            {remainingText && (
              <div className="text-sm leading-relaxed text-foreground">
                {formatInlineMarkdown(remainingText)}
              </div>
            )}
          </div>
        );
      }

      return (
        <p
          key={blockIndex}
          className="mb-2 text-sm leading-relaxed text-foreground"
        >
          {formatInlineMarkdown(trimmedBlock)}
        </p>
      );
    })
    .filter(Boolean);
}

/**
 * Handles the inline markdown subset currently emitted by the backend responses.
 */
function formatInlineMarkdown(text: string) {
  const parts: Array<string | JSX.Element> = [];
  let lastIndex = 0;
  const boldPattern = /\*\*(.+?)\*\*/g;
  let match: RegExpExecArray | null;

  while ((match = boldPattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      const beforeText = text.substring(lastIndex, match.index);
      parts.push(...formatLineBreaks(beforeText, parts.length));
    }

    parts.push(
      <strong key={`bold-${match.index}`} className="font-semibold">
        {match[1]}
      </strong>,
    );

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(...formatLineBreaks(text.substring(lastIndex), parts.length));
  }

  return parts;
}

/**
 * Preserves backend line breaks without promoting the whole answer to preformatted text.
 */
function formatLineBreaks(text: string, startKey: number) {
  const lines = text.split("\n");
  const result: Array<string | JSX.Element> = [];

  lines.forEach((line, index) => {
    if (index > 0) {
      result.push(<br key={`br-${startKey}-${index}`} />);
    }
    if (line) {
      result.push(line);
    }
  });

  return result;
}
