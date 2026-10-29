"use client";

import { LazyErrorScreen } from "@/components/LazyErrorScreen";

/** A public page failed to render (for example the second-factor page's session check timed out). */
export default function PublicError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <LazyErrorScreen retry={retry} />;
}
