import { createContext, useContext } from "react"

type Theme = "dark" | "light" | "system"

interface ThemeProviderState {
    theme: Theme
    setTheme: (theme: Theme) => void
}

const initialState: ThemeProviderState = {
    theme: "system",
    setTheme: () => null,
}

// Export context for theme provider to use
export const ThemeProviderContext = createContext<ThemeProviderState>(initialState)

/**
 * Hook to access theme context.
 * Use this to get/set the current theme.
 */
export const useTheme = () => {
    const context = useContext(ThemeProviderContext)

    if (context === undefined)
        throw new Error("useTheme must be used within a ThemeProvider")

    return context
}
