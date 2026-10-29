import type { ReactNode } from "react";

/**
 * The production stand-in for layout.lab.tsx (next.config.ts, pageExtensions): no fonts, no token sheet. It exists so
 * the route set, and with it Next's generated route types, are the same in development and production; the pages
 * under it answer 404 (page.stub.tsx).
 */
export default function DesignLabStubLayout({ children }: { children: ReactNode }) {
  return children;
}
