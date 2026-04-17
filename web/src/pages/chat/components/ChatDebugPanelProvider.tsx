import { useCallback, useMemo, useState, type ReactNode } from "react";

import {
  ChatDebugPanelContext,
  type ChatDebugPanelContextValue,
  type RegisteredChatDebugPanelSection,
} from "./ChatDebugPanelContext";

/**
 * Provide a small registry that lets descendants contribute debug-panel
 * sections upward to the outer ReactChatInterface shell.
 */
export function ChatDebugPanelProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [sectionsByKey, setSectionsByKey] = useState<
    Record<string, RegisteredChatDebugPanelSection>
  >({});

  const upsertSection = useCallback(
    (key: string, section: RegisteredChatDebugPanelSection) => {
      setSectionsByKey((previous) => ({
        ...previous,
        [key]: section,
      }));
    },
    [],
  );

  const removeSection = useCallback((key: string) => {
    setSectionsByKey((previous) => {
      if (!(key in previous)) {
        return previous;
      }

      const nextSections = { ...previous };
      delete nextSections[key];
      return nextSections;
    });
  }, []);

  const value = useMemo<ChatDebugPanelContextValue>(() => {
    const sections = Object.entries(sectionsByKey).map(([key, section]) => ({
      key,
      ...section,
    }));

    return {
      sections,
      upsertSection,
      removeSection,
    };
  }, [removeSection, sectionsByKey, upsertSection]);

  return (
    <ChatDebugPanelContext.Provider value={value}>
      {children}
    </ChatDebugPanelContext.Provider>
  );
}
