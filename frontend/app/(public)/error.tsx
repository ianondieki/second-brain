"use client";

import { ErrorScreen } from "@/components/ErrorScreen";

/** A public page failed to render (for example the second-factor page's session check timed out). */
export default function PublicError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <ErrorScreen retry={retry} />;
}
