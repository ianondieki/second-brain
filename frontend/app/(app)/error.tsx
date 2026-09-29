"use client";

import { LazyErrorScreen } from "@/components/LazyErrorScreen";

/** A signed-in page failed to render (for example GET /api/auth/me timed out). */
export default function SignedInError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <LazyErrorScreen retry={retry} />;
}
