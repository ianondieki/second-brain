"use client";

import { useEffect, useLayoutEffect, useSyncExternalStore, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { focusPageTitle } from "@/lib/focus";
import { haptic } from "@/lib/haptics";

import {
  celebrationCookieSet,
  celebrationSeen,
  clearCelebrationMarker,
  dismissCelebration,
  rememberCelebrationCookie,
  subscribeCelebration,
} from "./celebration-store";

/**
 * The thin client half of the closed-engagement celebration (ClosedCelebration.tsx draws the card on the server):
 * whether it is still shown, the buzz under the thumb, and the one button that puts it away. Kept small on purpose:
 * the tracker's routes sit close to the 150 KB JS budget (AC-UX-3), and the seal, the confetti and the words cost
 * nothing here.
 */
export function CelebrationShell({
  engagementId,
  initialSeen,
  dismiss,
  children,
}: {
  engagementId: string;
  initialSeen: boolean;
  dismiss: string;
  children: ReactNode;
}) {
  const seen = useSyncExternalStore(subscribeCelebration, () => celebrationSeen(engagementId), () => initialSeen);
  // The before-paint hide (CELEBRATION_INIT_SCRIPT) steps aside once what is drawn follows the store. A marker another
  // page left (a tracker that is not closed, a 404) goes before the first paint, so an unseen card is never painted
  // hidden; the marker for a card storage remembers stays until the passive effect, after hydration has removed the
  // card (Next hydrates in a transition, whose store check runs then), so that card is never painted at all.
  useLayoutEffect(() => {
    if (!celebrationSeen(engagementId)) clearCelebrationMarker();
  }, [engagementId]);
  useEffect(() => {
    clearCelebrationMarker();
    if (!seen) haptic("success");
    // Storage remembers longer than a cookie set from a page may: write the cookie again when it lapsed.
    else if (!celebrationCookieSet(engagementId)) rememberCelebrationCookie(engagementId);
  }, [seen, engagementId]);
  if (seen) return null;
  // One element for the card and its button: the before-paint hide (globals.css) covers both, never the card alone.
  return (
    <div data-celebration-shell="">
      {children}
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
  );
}
