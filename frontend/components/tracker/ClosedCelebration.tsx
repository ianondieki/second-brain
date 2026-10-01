"use client";

import { useEffect, useSyncExternalStore } from "react";

import { Seal } from "@/components/brand/Seal";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { CheckIcon } from "@/components/ui/status-icons";
import { focusPageTitle } from "@/lib/focus";
import { haptic } from "@/lib/haptics";

import {
  celebrationCookieSet,
  celebrationSeen,
  dismissCelebration,
  rememberCelebrationCookie,
  subscribeCelebration,
} from "./celebration-store";

export { dismissCelebration };


export interface ClosedCelebrationProps {
  engagementId: string;
  /** The server's answer, from the cookie: the card arrives with the page or not at all, so nothing shifts. */
  initialSeen?: boolean;
  title: string;
  body: string;
  dismiss: string;
}

/**
 * The one-time celebration of a closed engagement (D-52, feel): the seal draws its ring once, a few lattice-coloured
 * dots fall (still under reduced motion), a short buzz on phones (only after a tap: browsers refuse it before one), and
 * one button to put it away, after which focus returns to the page's title. Shown the first time this device opens a
 * CLOSED tracker, then remembered; the stage chip and the timeline say "Closed" on every visit.
 */
export function ClosedCelebration({ engagementId, initialSeen = true, title, body, dismiss }: ClosedCelebrationProps) {
  const seen = useSyncExternalStore(subscribeCelebration, () => celebrationSeen(engagementId), () => initialSeen);
  useEffect(() => {
    if (!seen) haptic("success");
    // Storage remembers longer than a cookie set from a page may: write the cookie again when it lapsed.
    else if (!celebrationCookieSet(engagementId)) rememberCelebrationCookie(engagementId);
  }, [seen, engagementId]);
  if (seen) return null;
  return (
    <Card
      as="section"
      aria-labelledby="closed-celebration-title"
      data-celebration={engagementId}
      className="relative mt-6 max-w-3xl overflow-hidden"
    >
      <span aria-hidden="true" className="confetti pointer-events-none absolute inset-x-0 top-0 h-full">
        {Array.from({ length: 12 }, (_, index) => (
          <i key={index} style={{ left: `${6 + index * 7.8}%`, animationDelay: `${(index % 4) * 120}ms` }} />
        ))}
      </span>
      <div className="relative flex flex-col items-start gap-5 sm:flex-row sm:items-center sm:gap-6">
        <Seal size={88} animate className="shrink-0" />
        <div className="min-w-0 flex-1">
          <h2 id="closed-celebration-title" className="flex items-center gap-2 text-lg text-ink">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-warm-wash text-warm">
              <CheckIcon className="size-4" />
            </span>
            {title}
          </h2>
          <p className="mt-2 max-w-[60ch] text-ink-soft">{body}</p>
          <div className="mt-4">
            <Button
              variant="secondary"
              onClick={() => {
                dismissCelebration(engagementId);
                focusPageTitle();
              }}
            >
              {dismiss}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
