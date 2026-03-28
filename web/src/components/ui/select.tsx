import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Check, ChevronDown, ChevronUp } from "@/lib/lucide"

import { cn } from "@/lib/utils"

type SelectSize = "large" | "medium" | "small"

const SELECT_TRIGGER_SIZE_CLASSES: Record<SelectSize, string> = {
    large: "h-9 gap-2 px-3 py-2 text-sm [&>svg]:h-4 [&>svg]:w-4",
    medium: "h-8 gap-1.5 px-2.5 py-1.5 text-[13px] [&>svg]:h-3.5 [&>svg]:w-3.5",
    small: "h-7 gap-1.5 px-2 py-1 text-xs [&>svg]:h-3 [&>svg]:w-3",
}

const SELECT_CONTENT_SIZE_CLASSES: Record<SelectSize, string> = {
    large: "min-w-[8rem]",
    medium: "min-w-[7rem]",
    small: "min-w-[6rem]",
}

const SELECT_VIEWPORT_SIZE_CLASSES: Record<SelectSize, string> = {
    large: "p-1",
    medium: "p-0.5",
    small: "p-0.5",
}

const SELECT_LABEL_SIZE_CLASSES: Record<SelectSize, string> = {
    large: "px-2 py-1.5 text-sm",
    medium: "px-1.5 py-1 text-[13px]",
    small: "px-1.5 py-0.5 text-xs",
}

const SELECT_ITEM_SIZE_CLASSES: Record<SelectSize, string> = {
    large: "py-1.5 pl-2 pr-8 text-sm",
    medium: "py-1 pl-1.5 pr-7 text-[13px]",
    small: "py-0.5 pl-1.5 pr-6 text-xs",
}

const SELECT_INDICATOR_SIZE_CLASSES: Record<SelectSize, string> = {
    large: "right-2 h-3.5 w-3.5",
    medium: "right-1.5 h-3 w-3",
    small: "right-1.5 h-2.5 w-2.5",
}

/**
 * Why: select menus should scale as one unit so the trigger and its dropdown
 * remain visually consistent without every caller wiring duplicate props.
 */
const SelectSizeContext = React.createContext<SelectSize>("large")

function useSelectSize(size?: SelectSize): SelectSize {
    const inheritedSize = React.useContext(SelectSizeContext)
    return size ?? inheritedSize
}

const Select = SelectPrimitive.Root

const SelectGroup = SelectPrimitive.Group

const SelectValue = SelectPrimitive.Value

/**
 * Select trigger button.
 */
const SelectTrigger = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Trigger>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger> & {
        size?: SelectSize
    }
>(({ className, children, size, ...props }, ref) => {
    const resolvedSize = useSelectSize(size)

    return (
        <SelectSizeContext.Provider value={resolvedSize}>
            <SelectPrimitive.Trigger
                ref={ref}
                className={cn(
                    "flex w-full items-center whitespace-nowrap rounded-md border border-input bg-transparent shadow-sm ring-offset-background transition-colors placeholder:text-muted-foreground hover:border-ring focus:outline-none focus:border-ring focus:ring-0 focus:shadow-none disabled:cursor-not-allowed disabled:opacity-50 [&>span:first-child]:min-w-0 [&>span:first-child]:flex-1 [&>span:first-child]:justify-start [&>span:first-child]:text-left [&>span:first-child]:truncate [&>span[data-placeholder]]:text-muted-foreground",
                    SELECT_TRIGGER_SIZE_CLASSES[resolvedSize],
                    className
                )}
                {...props}
            >
                {children}
                <SelectPrimitive.Icon asChild>
                    <ChevronDown className="shrink-0 opacity-50" />
                </SelectPrimitive.Icon>
            </SelectPrimitive.Trigger>
        </SelectSizeContext.Provider>
    )
})
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName

/**
 * Select scroll up button.
 */
const SelectScrollUpButton = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.ScrollUpButton
        ref={ref}
        className={cn(
            "flex cursor-default items-center justify-center py-1",
            className
        )}
        {...props}
    >
        <ChevronUp className="h-4 w-4" />
    </SelectPrimitive.ScrollUpButton>
))
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName

/**
 * Select scroll down button.
 */
const SelectScrollDownButton = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.ScrollDownButton
        ref={ref}
        className={cn(
            "flex cursor-default items-center justify-center py-1",
            className
        )}
        {...props}
    >
        <ChevronDown className="h-4 w-4" />
    </SelectPrimitive.ScrollDownButton>
))
SelectScrollDownButton.displayName =
    SelectPrimitive.ScrollDownButton.displayName

/**
 * Select content dropdown.
 */
const SelectContent = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content> & {
        size?: SelectSize
    }
>(({ className, children, position = "popper", size, ...props }, ref) => {
    const resolvedSize = useSelectSize(size)

    return (
        <SelectSizeContext.Provider value={resolvedSize}>
            <SelectPrimitive.Portal>
                <SelectPrimitive.Content
                    ref={ref}
                    className={cn(
                        // Draggable dialogs can keep increasing their z-index while focused.
                        // Keep select menus in a dedicated top layer so the popper never renders behind them.
                        "relative !z-[9999] max-h-96 overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
                        SELECT_CONTENT_SIZE_CLASSES[resolvedSize],
                        position === "popper" &&
                        "w-[var(--radix-select-trigger-width)] data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
                        className
                    )}
                    position={position}
                    {...props}
                >
                    <SelectScrollUpButton />
                    <SelectPrimitive.Viewport
                        className={cn(
                            SELECT_VIEWPORT_SIZE_CLASSES[resolvedSize],
                            position === "popper" &&
                            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
                        )}
                    >
                        {children}
                    </SelectPrimitive.Viewport>
                    <SelectScrollDownButton />
                </SelectPrimitive.Content>
            </SelectPrimitive.Portal>
        </SelectSizeContext.Provider>
    )
})
SelectContent.displayName = SelectPrimitive.Content.displayName

/**
 * Select label for option groups.
 */
const SelectLabel = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Label>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label> & {
        size?: SelectSize
    }
>(({ className, size, ...props }, ref) => {
    const resolvedSize = useSelectSize(size)

    return (
        <SelectPrimitive.Label
            ref={ref}
            className={cn(
                "font-semibold",
                SELECT_LABEL_SIZE_CLASSES[resolvedSize],
                className
            )}
            {...props}
        />
    )
})
SelectLabel.displayName = SelectPrimitive.Label.displayName

/**
 * Select item option.
 */
const SelectItem = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Item>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & {
        size?: SelectSize
    }
>(({ className, children, size, ...props }, ref) => {
    const resolvedSize = useSelectSize(size)

    return (
        <SelectPrimitive.Item
            ref={ref}
            className={cn(
                "relative flex w-full cursor-default select-none items-center overflow-hidden rounded-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                SELECT_ITEM_SIZE_CLASSES[resolvedSize],
                className
            )}
            {...props}
        >
            <span
                className={cn(
                    "absolute flex items-center justify-center",
                    SELECT_INDICATOR_SIZE_CLASSES[resolvedSize]
                )}
            >
                <SelectPrimitive.ItemIndicator>
                    <Check className="h-4 w-4" />
                </SelectPrimitive.ItemIndicator>
            </span>
            <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
        </SelectPrimitive.Item>
    )
})
SelectItem.displayName = SelectPrimitive.Item.displayName

/**
 * Select separator between groups.
 */
const SelectSeparator = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Separator>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.Separator
        ref={ref}
        className={cn("-mx-1 my-1 h-px bg-muted", className)}
        {...props}
    />
))
SelectSeparator.displayName = SelectPrimitive.Separator.displayName

export {
    Select,
    SelectGroup,
    SelectValue,
    SelectTrigger,
    SelectContent,
    SelectLabel,
    SelectItem,
    SelectSeparator,
    SelectScrollUpButton,
    SelectScrollDownButton,
}
