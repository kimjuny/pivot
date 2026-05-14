import { useEffect, useRef } from "react";

/**
 * Registers a global Cmd/Ctrl+K shortcut that invokes the given callback.
 * Uses a ref internally so the callback can reference fresh closure state
 * without re-registering the listener on every render.
 */
export function useNewSessionShortcut(callback: () => void) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        callbackRef.current();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);
}
