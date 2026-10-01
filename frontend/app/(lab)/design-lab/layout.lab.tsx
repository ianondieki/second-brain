import type { ReactNode } from "react";

/** The lab's root (development only; next.config.ts): the app's own tokens, fonts and theme apply, nothing is added. */
export default function DesignLabLayout({ children }: { children: ReactNode }) {
  return children;
}
