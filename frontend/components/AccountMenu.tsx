"use client";

import { useSearchParams } from "next/navigation";
import { lazy, Suspense, use, useEffect, useId, useRef, useState } from "react";

import { forgetEmail } from "@/lib/auth/remembered-email";

import { MenuOptions } from "./AccountMenuScope";
import { menuBillingHref } from "./billing-link";
import { forgetRecent } from "./palette/remember";
import { useStrings } from "./ClientStrings";
import { cn } from "./ui/cn";
import { Icon, type IconProps } from "./ui/status-icons";

function PersonIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="7" r="3.25" />
      <path d="M3.75 16.75c.9-2.9 3.3-4.5 6.25-4.5s5.35 1.6 6.25 4.5" />
    </Icon>
  );
}

function ChevronIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m5.75 8 4.25 4.25L14.25 8" />
    </Icon>
  );
}

const SECURITY_HREF = "/settings/security";
const NOTIFICATIONS_HREF = "/settings/notifications";

const HELP_HREF = "/help";

// The lower part loads on use. When its file cannot be fetched (offline, or a newer deploy replaced it), the menu keeps a
// plain Sign out of its own instead of failing the page.
export const loadExtras = () => import("./AccountMenuExtras").then((m) => m.AccountMenuExtras, () => MenuFallback);
const MenuExtras = lazy(() => loadExtras().then((component) => ({ default: component })));

/** The menu's own Sign out when the lower part could not load: the session's CSRF token from its cookie, then home. */
export function MenuFallback() {
  const t = useStrings("shell");
  const [failed, setFailed] = useState(false);
  async function signOut() {
    const pick = () => document.cookie.match(/(?:^|; )(?:__Host-)?bridge_csrf=([^;]*)/)?.[1];
    if (!pick()) await fetch("/api/auth/csrf", { credentials: "same-origin" }).catch(() => null);
    const token = pick();
    const response = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: token ? { "X-CSRF-Token": decodeURIComponent(token) } : {},
    }).catch(() => null);
    if (response?.status === 204 || response?.status === 401) {
      forgetEmail();
      forgetRecent();
      // A full load, as the top bar ships no router code (this is the rare path where the menu's own part is missing).
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login");
    } else setFailed(true);
  }
  return (
    <div className="mt-1 border-t border-line pt-1" data-menu-fallback="">
      <button type="button" className={itemClass} onClick={() => void signOut()}>
        {failed ? t("signOutRetry") : t("signOut")}
      </button>
    </div>
  );
}

const itemClass = "flex min-h-11 w-full items-center rounded-control px-3 font-medium text-ink no-underline hover:bg-accent-wash";

// The popover floats over the page: the one elevation (shadow-overlay, docs/platform/design/p16-design-system.md).

/**
 * The avatar menu of the top bar (docs/spec/07 item 1): Plan & billing, Notification settings, Help, then Sign out. A disclosure button with a list
 * of links (not an ARIA menu): Escape closes it and returns focus to the button, as does a press outside it. Plain
 * links, so the top bar ships no router code (this is on every signed-in page, docs/spec/07 item 5).
 */
export function AccountMenu() {
  const t = useStrings("shell");
  const { billing: showBilling } = use(MenuOptions);
  const [open, setOpen] = useState(false);
  const [primed, setPrimed] = useState(false);
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  // Organisation screens carry the organisation as ?org= (members of several): Plan & billing keeps it.
  const billing = menuBillingHref(useSearchParams().get("org"));

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    }
    function onPointer(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onFocus(event: FocusEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("focusin", onFocus);
    };
  }, [open]);

  return (
    <div ref={root} className="relative" data-account-menu="">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          setPrimed(true);
          setOpen((was) => !was);
        }}
        onPointerEnter={() => setPrimed(true)}
        onFocus={() => setPrimed(true)}
        className="-mr-2 inline-flex min-h-11 items-center gap-2 rounded-control px-2 font-medium text-ink hover:bg-accent-wash"
      >
        <span className="flex size-8 items-center justify-center rounded-full bg-accent-wash text-accent">
          <PersonIcon className="size-5" />
        </span>
        {/* Under 640 px the avatar carries the name alone, so the working name keeps one line. */}
        <span className="sr-only sm:not-sr-only">{t("account")}</span>
        <ChevronIcon className={cn("size-4 text-ink-soft transition-transform motion-reduce:transition-none", open && "rotate-180")} />
      </button>
      <div
        id={panelId}
        hidden={!open}
        className="absolute top-full right-0 z-20 mt-1 w-64 max-w-[calc(100vw-2rem)] rounded-control border border-line bg-field p-2 shadow-overlay"
      >
        <ul className="flex flex-col">
          {showBilling ? (
            <li>
              <a href={billing} className={itemClass}>
                {t("billing")}
              </a>
            </li>
          ) : null}
          <li>
            <a href={SECURITY_HREF} className={itemClass}>
              {t("security")}
            </a>
          </li>
          <li>
            <a href={NOTIFICATIONS_HREF} className={itemClass}>
              {t("notifications")}
            </a>
          </li>
          <li>
            <a href={HELP_HREF} className={itemClass}>
              {t("help")}
            </a>
          </li>
        </ul>
        {/* The appearance and Sign out load with the menu's first opening (or as the pointer or focus reaches its
            button): about 2 KB of script no page needs before then (docs/spec/07 item 5; P25). */}
        {primed ? (
          <Suspense fallback={<div className="h-32" aria-hidden="true" />}>
            <MenuExtras />
          </Suspense>
        ) : null}
      </div>
    </div>
  );
}
