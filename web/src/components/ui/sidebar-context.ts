import { createContext } from 'react'

/**
 * Sidebar context type definition.
 */
export type SidebarContextType = {
    state: 'expanded' | 'collapsed'
    open: boolean
    setOpen: (open: boolean) => void
    openMobile: boolean
    setOpenMobile: (open: boolean) => void
    isMobile: boolean
    toggleSidebar: () => void
}

/**
 * Context for sidebar state management.
 * Used by SidebarProvider and useSidebar hook.
 */
export const SidebarContext = createContext<SidebarContextType | null>(null)
