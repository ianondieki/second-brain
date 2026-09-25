import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};

/** False in the server HTML and during hydration, true once React runs in the browser. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
}
