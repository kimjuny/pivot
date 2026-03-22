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

export {}
