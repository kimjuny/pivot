import * as React from "react"
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu"
import { Check, ChevronRight, Circle } from "@/lib/lucide"

import { cn } from "@/lib/utils"

type DropdownMenuSize = "large" | "medium" | "small"

const DROPDOWN_MENU_CONTENT_SIZE_CLASSES: Record<DropdownMenuSize, string> = {
    large: "min-w-[8rem] p-1",
    medium: "min-w-[7rem] p-0.5",
    small: "min-w-[6rem] p-0.5",
}

const DROPDOWN_MENU_ITEM_SIZE_CLASSES: Record<DropdownMenuSize, string> = {
    large: "gap-2 px-2 py-1.5 text-sm [&>svg]:size-4",
    medium: "gap-1.5 px-1.5 py-1 text-[13px] [&>svg]:size-3.5",
    small: "gap-1.5 px-1.5 py-0.5 text-xs [&>svg]:size-3",
}

const DROPDOWN_MENU_INDICATOR_SIZE_CLASSES: Record<DropdownMenuSize, string> = {
    large: "left-2 h-3.5 w-3.5",
    medium: "left-1.5 h-3 w-3",
    small: "left-1.5 h-2.5 w-2.5",
}

const DROPDOWN_MENU_ITEM_INSET_CLASSES: Record<DropdownMenuSize, string> = {
    large: "pl-8",
    medium: "pl-7",
    small: "pl-6",
}

const DROPDOWN_MENU_CHECKBOX_ITEM_SIZE_CLASSES: Record<
    DropdownMenuSize,
    string
> = {
    large: "py-1.5 pl-8 pr-2 text-sm",
    medium: "py-1 pl-7 pr-1.5 text-[13px]",
    small: "py-0.5 pl-6 pr-1.5 text-xs",
}

const DROPDOWN_MENU_LABEL_SIZE_CLASSES: Record<DropdownMenuSize, string> = {
    large: "px-2 py-1.5 text-sm",
    medium: "px-1.5 py-1 text-[13px]",
    small: "px-1.5 py-0.5 text-xs",
}

const DROPDOWN_MENU_SHORTCUT_SIZE_CLASSES: Record<DropdownMenuSize, string> = {
    large: "text-xs tracking-widest",
    medium: "text-xs tracking-wide",
    small: "text-[11px] tracking-wide",
}

/**
 * Why: most menus want one size decision at the container level so every item
 * stays visually aligned without repeating props on each child.
 */
const DropdownMenuSizeContext = React.createContext<DropdownMenuSize>("medium")

function useDropdownMenuSize(size?: DropdownMenuSize): DropdownMenuSize {
    const inheritedSize = React.useContext(DropdownMenuSizeContext)
    return size ?? inheritedSize
}

const DropdownMenu = DropdownMenuPrimitive.Root

const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger

const DropdownMenuGroup = DropdownMenuPrimitive.Group

const DropdownMenuPortal = DropdownMenuPrimitive.Portal

const DropdownMenuSub = DropdownMenuPrimitive.Sub

const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup

/**
 * DropdownMenu sub-trigger for nested menus.
 */
const DropdownMenuSubTrigger = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.SubTrigger>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
        inset?: boolean
        size?: DropdownMenuSize
    }
>(({ className, inset, children, size, ...props }, ref) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <DropdownMenuPrimitive.SubTrigger
            ref={ref}
            className={cn(
                "flex cursor-default select-none items-center rounded-sm outline-none focus:bg-accent data-[state=open]:bg-accent [&_svg]:pointer-events-none [&_svg]:shrink-0",
                DROPDOWN_MENU_ITEM_SIZE_CLASSES[resolvedSize],
                inset && DROPDOWN_MENU_ITEM_INSET_CLASSES[resolvedSize],
                className
            )}
            {...props}
        >
            {children}
            <ChevronRight className="ml-auto" />
        </DropdownMenuPrimitive.SubTrigger>
    )
})
DropdownMenuSubTrigger.displayName =
    DropdownMenuPrimitive.SubTrigger.displayName

/**
 * DropdownMenu sub-content for nested menus.
 */
const DropdownMenuSubContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.SubContent>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent> & {
        size?: DropdownMenuSize
    }
>(({ className, size, ...props }, ref) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <DropdownMenuSizeContext.Provider value={resolvedSize}>
            <DropdownMenuPrimitive.SubContent
                ref={ref}
                className={cn(
                    "!z-[9999] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-lg data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
                    DROPDOWN_MENU_CONTENT_SIZE_CLASSES[resolvedSize],
                    className
                )}
                {...props}
            />
        </DropdownMenuSizeContext.Provider>
    )
})
DropdownMenuSubContent.displayName =
    DropdownMenuPrimitive.SubContent.displayName

/**
 * DropdownMenu content container.
 */
const DropdownMenuContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content> & {
        size?: DropdownMenuSize
    }
>(({ className, sideOffset = 4, size, ...props }, ref) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <DropdownMenuSizeContext.Provider value={resolvedSize}>
            <DropdownMenuPrimitive.Portal>
                <DropdownMenuPrimitive.Content
                    ref={ref}
                    sideOffset={sideOffset}
                    className={cn(
                        // Draggable dialogs can keep increasing their z-index while focused.
                        // Keep dropdowns in a dedicated top layer so menus never slip behind them.
                        "!z-[9999] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md",
                        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
                        DROPDOWN_MENU_CONTENT_SIZE_CLASSES[resolvedSize],
                        className
                    )}
                    {...props}
                />
            </DropdownMenuPrimitive.Portal>
        </DropdownMenuSizeContext.Provider>
    )
})
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName

/**
 * DropdownMenu item option.
 */
const DropdownMenuItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Item>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
        inset?: boolean
        size?: DropdownMenuSize
    }
>(({ className, inset, size, ...props }, ref) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <DropdownMenuPrimitive.Item
            ref={ref}
            className={cn(
                "relative flex cursor-default select-none items-center rounded-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&>svg]:shrink-0",
                DROPDOWN_MENU_ITEM_SIZE_CLASSES[resolvedSize],
                inset && DROPDOWN_MENU_ITEM_INSET_CLASSES[resolvedSize],
                className
            )}
            {...props}
        />
    )
})
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName

/**
 * DropdownMenu checkbox item.
 */
const DropdownMenuCheckboxItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.CheckboxItem>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem> & {
        size?: DropdownMenuSize
    }
>(({ className, children, checked, size, ...props }, ref) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <DropdownMenuPrimitive.CheckboxItem
            ref={ref}
            className={cn(
                "relative flex cursor-default select-none items-center rounded-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                DROPDOWN_MENU_CHECKBOX_ITEM_SIZE_CLASSES[resolvedSize],
                className
            )}
            checked={checked}
            {...props}
        >
            <span
                className={cn(
                    "absolute flex items-center justify-center",
                    DROPDOWN_MENU_INDICATOR_SIZE_CLASSES[resolvedSize]
                )}
            >
                <DropdownMenuPrimitive.ItemIndicator>
                    <Check className="h-4 w-4" />
                </DropdownMenuPrimitive.ItemIndicator>
            </span>
            {children}
        </DropdownMenuPrimitive.CheckboxItem>
    )
})
DropdownMenuCheckboxItem.displayName =
    DropdownMenuPrimitive.CheckboxItem.displayName

/**
 * DropdownMenu radio item.
 */
const DropdownMenuRadioItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.RadioItem>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem> & {
        size?: DropdownMenuSize
    }
>(({ className, children, size, ...props }, ref) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <DropdownMenuPrimitive.RadioItem
            ref={ref}
            className={cn(
                "relative flex cursor-default select-none items-center rounded-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                DROPDOWN_MENU_CHECKBOX_ITEM_SIZE_CLASSES[resolvedSize],
                className
            )}
            {...props}
        >
            <span
                className={cn(
                    "absolute flex items-center justify-center",
                    DROPDOWN_MENU_INDICATOR_SIZE_CLASSES[resolvedSize]
                )}
            >
                <DropdownMenuPrimitive.ItemIndicator>
                    <Circle className="h-2 w-2 fill-current" />
                </DropdownMenuPrimitive.ItemIndicator>
            </span>
            {children}
        </DropdownMenuPrimitive.RadioItem>
    )
})
DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName

/**
 * DropdownMenu label for groups.
 */
const DropdownMenuLabel = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Label>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & {
        inset?: boolean
        size?: DropdownMenuSize
    }
>(({ className, inset, size, ...props }, ref) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <DropdownMenuPrimitive.Label
            ref={ref}
            className={cn(
                "font-semibold",
                DROPDOWN_MENU_LABEL_SIZE_CLASSES[resolvedSize],
                inset && DROPDOWN_MENU_ITEM_INSET_CLASSES[resolvedSize],
                className
            )}
            {...props}
        />
    )
})
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName

/**
 * DropdownMenu separator between items.
 */
const DropdownMenuSeparator = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Separator>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
    <DropdownMenuPrimitive.Separator
        ref={ref}
        className={cn("-mx-1 my-1 h-px bg-muted", className)}
        {...props}
    />
))
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName

/**
 * DropdownMenu keyboard shortcut indicator.
 */
const DropdownMenuShortcut = ({
    className,
    size,
    ...props
}: React.HTMLAttributes<HTMLSpanElement> & { size?: DropdownMenuSize }) => {
    const resolvedSize = useDropdownMenuSize(size)

    return (
        <span
            className={cn(
                "ml-auto opacity-60",
                DROPDOWN_MENU_SHORTCUT_SIZE_CLASSES[resolvedSize],
                className
            )}
            {...props}
        />
    )
}
DropdownMenuShortcut.displayName = "DropdownMenuShortcut"

export {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuCheckboxItem,
    DropdownMenuRadioItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuGroup,
    DropdownMenuPortal,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuRadioGroup,
}
