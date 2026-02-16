import { create } from 'zustand';

/**
 * Represents a tab in the agent detail page.
 * Each tab can display different content types: scenes, functions, or skills.
 */
export interface AgentTab {
    id: string;
    type: 'scene' | 'function' | 'skill';
    name: string;
    /** ID of the resource being displayed (scene ID, function ID, etc.) */
    resourceId: number | string;
}

interface AgentTabStore {
    /** List of open tabs */
    tabs: AgentTab[];
    /** Currently active tab ID */
    activeTabId: string | null;

    /** Add a new tab or activate existing one */
    openTab: (tab: Omit<AgentTab, 'id'>) => void;
    /** Close a tab by ID */
    closeTab: (id: string) => void;
    /** Set the active tab */
    setActiveTab: (id: string) => void;
    /** Close all tabs */
    closeAllTabs: () => void;
    /** Replace a tab's resource ID (e.g. after a new scene is saved and gets a real ID) */
    replaceTabResource: (oldResourceId: number | string, newResourceId: number | string, type: 'scene' | 'function' | 'skill') => void;
}

/**
 * Store for managing tabs in the agent detail page.
 * Handles opening, closing, and switching between different resource tabs.
 */
export const useAgentTabStore = create<AgentTabStore>((set, get) => ({
    tabs: [],
    activeTabId: null,

    openTab: (tabData) => {
        const { tabs } = get();

        // Generate unique ID based on type and resource ID
        const tabId = `${tabData.type}-${tabData.resourceId}`;

        // Check if tab already exists
        const existingTab = tabs.find(tab => tab.id === tabId);

        if (existingTab) {
            // Tab exists, just activate it
            set({ activeTabId: tabId });
        } else {
            // Create new tab
            const newTab: AgentTab = {
                id: tabId,
                ...tabData,
            };

            set({
                tabs: [...tabs, newTab],
                activeTabId: tabId,
            });
        }
    },

    closeTab: (id) => {
        const { tabs, activeTabId } = get();
        const newTabs = tabs.filter(tab => tab.id !== id);

        // If closing the active tab, switch to another tab
        let newActiveTabId = activeTabId;
        if (activeTabId === id) {
            if (newTabs.length > 0) {
                // Find the tab that was before the closed one, or use the first tab
                const closedIndex = tabs.findIndex(tab => tab.id === id);
                const newIndex = Math.max(0, closedIndex - 1);
                newActiveTabId = newTabs[newIndex]?.id || null;
            } else {
                newActiveTabId = null;
            }
        }

        set({
            tabs: newTabs,
            activeTabId: newActiveTabId,
        });
    },

    setActiveTab: (id) => {
        set({ activeTabId: id });
    },

    replaceTabResource: (oldResourceId, newResourceId, type) => {
        const { tabs, activeTabId } = get();
        const oldTabId = `${type}-${oldResourceId}`;
        const newTabId = `${type}-${newResourceId}`;

        // If new tab already exists (shouldn't happen usually), closes the old one
        // But here we want to mutate the old one to the new one

        const updatedTabs = tabs.map(tab => {
            if (tab.id === oldTabId) {
                return {
                    ...tab,
                    id: newTabId,
                    resourceId: newResourceId
                };
            }
            return tab;
        });

        // Update active ID if needed
        const newActiveTabId = activeTabId === oldTabId ? newTabId : activeTabId;

        set({
            tabs: updatedTabs,
            activeTabId: newActiveTabId
        });
    },

    closeAllTabs: () => {
        set({ tabs: [], activeTabId: null });
    },
}));
