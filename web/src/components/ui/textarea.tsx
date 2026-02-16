import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Textarea component with shadcn styling.
 * Uses standard HTML textarea element with enhanced focus states.
 */
const Textarea = React.forwardRef<
    HTMLTextAreaElement,
    React.ComponentProps<"textarea">
>(({ className, ...props }, ref) => {
    return (
        <textarea
            className={cn(
                "flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-sm transition-colors placeholder:text-muted-foreground hover:border-ring focus-visible:outline-none focus-visible:border-ring focus-visible:ring-0 focus-visible:shadow-none focus:border-ring focus:ring-0 focus:shadow-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
                className
            )}
            ref={ref}
            {...props}
        />
    )
})
Textarea.displayName = "Textarea"

export { Textarea }
