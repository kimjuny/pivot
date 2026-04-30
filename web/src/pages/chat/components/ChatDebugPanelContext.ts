import {
  createContext,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from "react";

/**
 * One extra section that child chat surfaces can contribute to the shared
 * debug panel without knowing how the host shell renders that panel.
 */
export interface ChatDebugPanelSection {
  /** Stable key used to upsert one section from one child owner. */
  key: string;
  /** Short heading rendered above the section content. */
  title: string;
  /** Optional helper copy that explains why the section exists. */
  description?: string;
  /** Arbitrary React content rendered inside the debug panel. */
  content: ReactNode;
}

export type RegisteredChatDebugPanelSection = Omit<
  ChatDebugPanelSection,
  "key"
>;

export interface ChatDebugPanelContextValue {
  /** Ordered panel sections currently registered by descendants. */
  sections: ChatDebugPanelSection[];
  /** Upsert one debug section owned by a descendant. */
  upsertSection: (
    key: string,
    section: RegisteredChatDebugPanelSection,
  ) => void;
  /** Remove one section when its owner unmounts or no longer applies. */
  removeSection: (key: string) => void;
}

const DEFAULT_CHAT_DEBUG_PANEL_CONTEXT: ChatDebugPanelContextValue = {
  sections: [],
  upsertSection: () => {},
  removeSection: () => {},
};

export const ChatDebugPanelContext =
  createContext<ChatDebugPanelContextValue>(
    DEFAULT_CHAT_DEBUG_PANEL_CONTEXT,
  );

/**
 * Read the currently registered debug-panel sections.
 *
 * Why: the outer chat shell owns the floating debug affordance, but nested page
 * components still need a clean path to surface development controls there.
 */
export function useChatDebugPanelSections(): ChatDebugPanelSection[] {
  return useContext(ChatDebugPanelContext).sections;
}

/**
 * Register one debug-panel section from a descendant while it is mounted.
 *
 * Why: local chat features such as surface development controls should be able
 * to extend the shared debug affordance without hard-coding those controls into
 * the top-level shell component.
 */
export function useRegisterChatDebugPanelSection(
  section: ChatDebugPanelSection | null,
): void {
  const { removeSection, upsertSection } = useContext(ChatDebugPanelContext);
  const registeredKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!section) {
      if (registeredKeyRef.current) {
        removeSection(registeredKeyRef.current);
        registeredKeyRef.current = null;
      }
      return;
    }

    const { key, ...restSection } = section;
    if (registeredKeyRef.current && registeredKeyRef.current !== key) {
      removeSection(registeredKeyRef.current);
    }
    registeredKeyRef.current = key;
    upsertSection(key, restSection);
  }, [removeSection, section, upsertSection]);

  useEffect(() => {
    return () => {
      if (registeredKeyRef.current) {
        removeSection(registeredKeyRef.current);
        registeredKeyRef.current = null;
      }
    };
  }, [removeSection]);
}
