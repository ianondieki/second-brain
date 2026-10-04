"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type MouseEvent, type ReactNode } from "react";

import { cn } from "@/components/ui/cn";

import { markRead } from "./calls";

export interface ReadLinkProps {
  id: string;
  href: string;
  unread: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Set when a row was recorded read and the person went on to its page. Back to the list restores the list as it was
 * shown (Next's router cache), with the row still unread: FreshOnReturn then reads the page again. Module state, so
 * it lives exactly as long as this document's soft navigations.
 */
let readSinceShown = false;

/**
 * On the Notifications page: after a row was opened and the person came back (Back, or the bell), the list and the
 * bell are read again (router.refresh), so the opened row no longer shows unread. Renders nothing.
 */
export function FreshOnReturn() {
  const router = useRouter();
  useEffect(() => {
    if (!readSinceShown) return;
    readSinceShown = false;
    router.refresh();
  }, [router]);
  return null;
}

/** A press that opens the link somewhere else (a new tab or window, a download): the browser handles it. */
function opensElsewhere(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
}

/**
 * A notification row's link (stretched over the row by its class): opening an unread one first records it as read
 * (POST …/read, bounded), then navigates, so the page it lands on already counts it in the bell. A read one is a
 * plain link; a press that opens a new tab (a modified click, or the middle button's auxclick) still records it and
 * reads this page again, so the row and the bell show it read. A failed write never stops the person: they are taken
 * where the row points either way.
 */
export function ReadLink({ id, href, unread, className, children }: ReadLinkProps) {
  const router = useRouter();
  const [opening, setOpening] = useState(false);

  /** Opened in another tab: recorded, then this page is read again. */
  async function readInPlace() {
    if (await markRead(id)) router.refresh();
  }

  async function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (!unread || event.defaultPrevented) return;
    if (opensElsewhere(event)) {
      void readInPlace();
      return;
    }
    event.preventDefault();
    if (opening) return;
    setOpening(true);
    if (await markRead(id)) readSinceShown = true;
    router.push(href);
  }

  /** The middle button fires auxclick, not click: it opens a new tab and marks the row read the same way. */
  function onAuxClick(event: MouseEvent<HTMLAnchorElement>) {
    if (unread && event.button === 1) void readInPlace();
  }

  return (
    <Link
      href={href}
      prefetch={false}
      onClick={onClick}
      onAuxClick={onAuxClick}
      className={className}
      aria-busy={opening || undefined}
    >
      {children}
      {/* The row's pending hint (LinkPending's look): shows while the read is recorded and the page is on its way. */}
      <span
        aria-hidden="true"
        data-opening={opening ? "true" : "false"}
        className={cn(
          "pointer-events-none absolute -top-px left-0 inline-block h-[3px] w-6 bg-accent transition-opacity duration-150",
          "ease-out motion-reduce:transition-none",
          opening ? "opacity-100 delay-100 motion-safe:animate-pulse" : "opacity-0",
        )}
      />
    </Link>
  );
}
