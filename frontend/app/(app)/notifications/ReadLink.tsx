"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type MouseEvent, type ReactNode } from "react";

import { cn } from "@/components/ui/cn";

import { markRead } from "./calls";

export interface ReadLinkProps {
  id: string;
  href: string;
  unread: boolean;
  className?: string;
  children: ReactNode;
}

/** A press that opens the link somewhere else (a new tab or window, a download): the browser handles it. */
function opensElsewhere(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
}

/**
 * A notification row's link (stretched over the row by its class): opening an unread one first records it as read
 * (POST …/read, bounded), then navigates, so the page it lands on already counts it in the bell. A read one is a
 * plain link; a press that opens a new tab still records it, and the page stays as it is. A failed write never
 * stops the person: they are taken where the row points either way.
 */
export function ReadLink({ id, href, unread, className, children }: ReadLinkProps) {
  const router = useRouter();
  const [opening, setOpening] = useState(false);

  async function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (!unread || event.defaultPrevented) return;
    if (opensElsewhere(event)) {
      void markRead(id);
      return;
    }
    event.preventDefault();
    if (opening) return;
    setOpening(true);
    await markRead(id);
    router.push(href);
  }

  return (
    <Link href={href} prefetch={false} onClick={onClick} className={className} aria-busy={opening || undefined}>
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
