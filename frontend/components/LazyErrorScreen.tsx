"use client";

import { lazy, Suspense } from "react";

// The route groups' error boundaries are part of every page's first download, but the screen only shows when a page
// failed to render; it loads then (docs/spec/07 item 5, the 150 KB JS budget; the browser is online in that case:
// the server could not render the page, or a client component threw).
const ErrorScreen = lazy(() => import("./ErrorScreen").then((m) => ({ default: m.ErrorScreen })));

export function LazyErrorScreen({ retry }: { retry: () => void }) {
  return (
    <Suspense fallback={null}>
      <ErrorScreen retry={retry} />
    </Suspense>
  );
}
