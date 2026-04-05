import 'react'

interface Window {
  location: Location & {
    pathname: string
  }
}

declare module 'react' {
  interface InputHTMLAttributes<T> {
    directory?: string
    webkitdirectory?: string
  }
}

declare module '@radix-ui/react-avatar' {
  import * as React from 'react'

  export const Root: React.ForwardRefExoticComponent<
    React.HTMLAttributes<HTMLSpanElement> &
      React.RefAttributes<HTMLSpanElement>
  >
  export const Image: React.ForwardRefExoticComponent<
    React.ImgHTMLAttributes<HTMLImageElement> &
      React.RefAttributes<HTMLImageElement>
  >
  export const Fallback: React.ForwardRefExoticComponent<
    React.HTMLAttributes<HTMLSpanElement> &
      React.RefAttributes<HTMLSpanElement>
  >
}

export {}
