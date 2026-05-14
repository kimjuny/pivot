import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { WorkspaceFileItem } from "@/utils/api";
import { searchWorkspaceFiles } from "@/utils/api";

/** Detected `@` token near the caret. */
export interface ActiveFileMention {
  /** Character index where the `@` token begins. */
  start: number;
  /** Character index where the query ends (caret position). */
  end: number;
  /** Text after `@`, used for filtering. */
  query: string;
}

/** File mention key for dismissal tracking. */
function fileMentionKey(m: ActiveFileMention): string {
  return `${m.start}:${m.query}`;
}

/**
 * Detects the active `@`-token near the caret so the composer can open the
 * file mention picker.
 */
export function getActiveFileMention(
  value: string,
  selectionStart: number,
): ActiveFileMention | null {
  const safeStart = Math.max(Math.min(selectionStart, value.length), 0);
  const beforeCaret = value.slice(0, safeStart);
  const tokenStart =
    Math.max(beforeCaret.lastIndexOf(" "), beforeCaret.lastIndexOf("\n")) + 1;
  const token = beforeCaret.slice(tokenStart);
  if (!token.startsWith("@")) {
    return null;
  }

  const query = token.slice(1);
  // Avoid triggering in email-like patterns.
  if (query.includes("@")) {
    return null;
  }

  return { start: tokenStart, end: safeStart, query };
}

/** Return type of the `useFileMention` hook. */
export interface UseFileMentionResult {
  /** Whether the picker popover is open. */
  isOpen: boolean;
  /** Current search results. */
  files: WorkspaceFileItem[];
  /** Whether a search request is in flight. */
  isLoading: boolean;
  /** Index of the keyboard-highlighted item. */
  highlightedIndex: number;
  /** Move highlight up/down. */
  setHighlightedIndex: (index: number) => void;
  /** Replace the `@query` token with the selected file path. */
  selectFile: (
    file: WorkspaceFileItem,
    textarea: HTMLTextAreaElement,
  ) => void;
  /** Dismiss the picker (Escape, arrow off token, etc.). */
  dismiss: () => void;
  /** The currently active mention token (null if no `@` token). */
  activeMention: ActiveFileMention | null;
}

/** Hook managing the `@` file-mention picker lifecycle. */
export function useFileMention(
  sessionId: string | null | undefined,
  draftMessage: string,
  selectionStart: number,
  isStreaming: boolean,
): UseFileMentionResult {
  const [files, setFiles] = useState<WorkspaceFileItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeMention = useMemo(
    () => (isStreaming ? null : getActiveFileMention(draftMessage, selectionStart)),
    [draftMessage, selectionStart, isStreaming],
  );

  const mentionKey = activeMention ? fileMentionKey(activeMention) : null;
  const isOpen = activeMention !== null && mentionKey !== dismissedKey;

  // Debounced search when query changes.
  useEffect(() => {
    if (!isOpen || !sessionId || activeMention === null) {
      setFiles([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setHighlightedIndex(0);

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    if (abortRef.current) {
      abortRef.current.abort();
    }

    const controller = new AbortController();
    abortRef.current = controller;

    const query = activeMention.query.trim();
    debounceRef.current = setTimeout(() => {
      searchWorkspaceFiles({ session_id: sessionId, q: query, limit: 20 })
        .then((result) => {
          if (!controller.signal.aborted) {
            setFiles(result.files);
            setIsLoading(false);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setFiles([]);
            setIsLoading(false);
          }
        });
    }, 300);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      controller.abort();
    };
  }, [isOpen, sessionId, activeMention]);

  // Reset dismissal when mention token changes.
  useEffect(() => {
    setDismissedKey(null);
  }, [mentionKey]);

  const dismiss = useCallback(() => {
    if (mentionKey) {
      setDismissedKey(mentionKey);
    }
  }, [mentionKey]);

  const selectFile = useCallback(
    (file: WorkspaceFileItem, textarea: HTMLTextAreaElement) => {
      if (activeMention === null) {
        return;
      }
      const before = draftMessage.slice(0, activeMention.start);
      const after = draftMessage.slice(activeMention.end);
      const newValue = `${before}${file.path} ${after}`;

      const newCursorPos = activeMention.start + file.path.length + 1;

      // Set the textarea value via the React-compatible native setter.
      const descriptor = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      );
      if (descriptor?.set) {
        descriptor.set.call(textarea, newValue);
      }
      textarea.dispatchEvent(new Event("input", { bubbles: true }));

      requestAnimationFrame(() => {
        textarea.focus();
        textarea.setSelectionRange(newCursorPos, newCursorPos);
      });
    },
    [draftMessage, activeMention],
  );

  return {
    isOpen,
    files,
    isLoading,
    highlightedIndex,
    setHighlightedIndex,
    selectFile,
    dismiss,
    activeMention,
  };
}
