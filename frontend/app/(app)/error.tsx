"use client";

import { ErrorScreen } from "@/components/ErrorScreen";

/** A signed-in page failed to render (for example GET /api/auth/me timed out). */
export default function SignedInError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <ErrorScreen retry={retry} />;
}
