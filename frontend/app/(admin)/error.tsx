"use client";

import { LazyErrorScreen } from "@/components/LazyErrorScreen";

/** A staff console page failed to render (for example the API did not answer in time). */
export default function StaffConsoleError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <LazyErrorScreen retry={retry} />;
}
