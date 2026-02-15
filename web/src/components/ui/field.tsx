import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Field component that groups form inputs with their labels.
 * Serves as a semantic wrapper for proper form structure.
 */
const Field = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<"div">
>(({ className, ...props }, ref) => {
    return (
        <div
            ref={ref}
            className={cn("flex flex-col gap-2", className)}
            {...props}
        />
    )
})
Field.displayName = "Field"

/**
 * Label component for form fields.
 * Associated with input via htmlFor attribute.
 */
const FieldLabel = React.forwardRef<
    HTMLLabelElement,
    React.ComponentProps<"label">
>(({ className, ...props }, ref) => {
    return (
        <label
            ref={ref}
            className={cn(
                "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
                className
            )}
            {...props}
        />
    )
})
FieldLabel.displayName = "FieldLabel"

export { Field, FieldLabel }
