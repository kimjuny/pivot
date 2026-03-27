declare module 'vaul' {
  import type * as React from 'react'

  export const Drawer: {
    Root: React.ComponentType<React.ComponentProps<'div'> & {
      open?: boolean
      defaultOpen?: boolean
      onOpenChange?: (open: boolean) => void
      shouldScaleBackground?: boolean
    }>
    Trigger: React.ComponentType<React.ComponentProps<'button'>>
    Portal: React.ComponentType<React.PropsWithChildren>
    Close: React.ComponentType<React.ComponentProps<'button'>>
    Overlay: React.ForwardRefExoticComponent<
      React.ComponentPropsWithoutRef<'div'> & React.RefAttributes<HTMLDivElement>
    >
    Content: React.ForwardRefExoticComponent<
      React.ComponentPropsWithoutRef<'div'> & React.RefAttributes<HTMLDivElement>
    >
    Title: React.ForwardRefExoticComponent<
      React.ComponentPropsWithoutRef<'div'> & React.RefAttributes<HTMLDivElement>
    >
    Description: React.ForwardRefExoticComponent<
      React.ComponentPropsWithoutRef<'div'> & React.RefAttributes<HTMLDivElement>
    >
  }
}
