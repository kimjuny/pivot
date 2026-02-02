import { Moon, Sun } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useTheme } from "@/lib/use-theme"

/**
 * Simple theme toggle button.
 * Clicking toggles between light and dark mode.
 * Shows sun icon in dark mode, moon icon in light mode.
 */
export function ModeToggle() {
    const { theme, setTheme } = useTheme()

    const toggleTheme = () => {
        // If current theme is dark (or system that resolves to dark), switch to light
        // Otherwise switch to dark
        if (theme === "dark") {
            setTheme("light")
        } else {
            setTheme("dark")
        }
    }

    return (
        <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
            {/* Sun icon - visible in dark mode (click to switch to light) */}
            <Sun className="h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            {/* Moon icon - visible in light mode (click to switch to dark) */}
            <Moon className="absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
            <span className="sr-only">Toggle theme</span>
        </Button>
    )
}
