import { Lattice } from "./Lattice";

/**
 * The loading state of a route group (Next's loading.tsx): the lattice band where the page's top bar will be, three
 * quiet bars for the title, lead and content, and "Loading…" for assistive technology. It never shows a spinner: the
 * page replaces it within a moment (docs/spec/07, states), and reduced motion stops the shimmer.
 */
/** `label`: "Loading…" in the page's language (the loading.tsx of each route group reads it). */
export function LoadingScreen({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="flex min-h-dvh flex-col bg-paper">
      <Lattice />
      <div className="mx-auto w-full max-w-6xl flex-1 px-4 pt-16 sm:px-6">
        <p className="sr-only">{label}</p>
        <div aria-hidden="true" className="flex max-w-xl flex-col gap-5">
          <span className="loading-bar h-8 w-2/3" />
          <span className="loading-bar h-4 w-full" />
          <span className="loading-bar h-4 w-5/6" />
          <span className="loading-bar mt-6 h-32 w-full rounded-panel" />
        </div>
      </div>
    </div>
  );
}
