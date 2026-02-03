import { useContext } from 'react'
import { SidebarContext } from '@/components/ui/sidebar-context'

/**
 * Hook to access sidebar context.
 * Must be used within a SidebarProvider.
 */
export function useSidebar() {
    const context = useContext(SidebarContext)
    if (!context) {
        throw new Error('useSidebar must be used within a SidebarProvider.')
    }
    return context
}
