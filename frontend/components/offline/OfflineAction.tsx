"use client";

import { useSyncExternalStore } from "react";

import { buttonClass } from "../ui/Button";

/**
 * Where the trackers kept on this device are listed, from the address that could not be loaded (the worker answers a
 * failed page load with /offline at that address): the developer's or the organisation's Engagements (with its
 * ?org=), or null when the portal is not known from it.
 */
export function engagementsFor(pathname: string, search: string): string | null {
  if (/^\/dev(?:\/|$)/.test(pathname)) return "/dev/engagements";
  if (!/^\/org(?:\/|$)/.test(pathname)) return null;
  const org = new URLSearchParams(search).get("org");
  return org ? `/org/engagements?org=${encodeURIComponent(org)}` : "/org/engagements";
}

const still = () => () => {};

/**
 * The /offline page's one action (P27): Engagements of the portal the address belongs to, else the home page. The
 * server and the first render say "home" (the address is only known in the browser), so hydration is unchanged.
 */
export function OfflineAction({ engagements, home }: { engagements: string; home: string }) {
  const href = useSyncExternalStore(
    still,
    () => engagementsFor(location.pathname, location.search),
    () => null,
  );
  return (
    // A full page load on purpose: the worker answers it from this device's copy when there is one.
    <a
      href={href ?? "/"}
      data-primary=""
      data-offline-action={href ? "engagements" : "home"}
      className={buttonClass("primary", "no-underline")}
    >
      {href ? engagements : home}
    </a>
  );
}
