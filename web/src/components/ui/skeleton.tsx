import { cn } from "@/lib/utils"

/**
 * Skeleton component for loading states.
 * Provides a pulsing placeholder animation.
 */
function Skeleton({
    className,
    ...props
}: React.HTMLAttributes<HTMLDivElement>) {
    return (
        <div
            className={cn("animate-pulse rounded-md bg-primary/10", className)}
            {...props}
        />
    )
}

export { Skeleton }
