"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * After an in-app navigation to another page, focus goes to the new page's h1 (or its <main>) once, so a keyboard or
 * screen-reader user continues from the top of the new page instead of from <body> (WCAG 2.4.3; P16-B ux-review).
 * Never on the first load (the browser starts at the top already), never for a change of the query alone (a tab of
 * the same page keeps focus on the tab), and never when the page or the tapped control already holds focus. In the
 * root layout, the one part of the tree that stays mounted across navigations.
 */
export function RouteFocus() {
  const pathname = usePathname();
  const shown = useRef(pathname);
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    const active = document.activeElement;
    if (active && active !== document.body && active.isConnected) return;
    const main = document.getElementById("main");
    const target = main?.querySelector<HTMLElement>("h1") ?? main;
    if (!target) return;
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.classList.add("focus:outline-none"); // a heading is not a control: no ring
    target.focus({ preventScroll: true });
  }, [pathname]);
  return null;
}
