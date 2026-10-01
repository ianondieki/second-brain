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
  // Mounted: what is drawn now follows the store, so the before-paint hide (CELEBRATION_INIT_SCRIPT) steps aside,
  // before the first paint (a layout effect), so a card another page's marker would hide is never painted hidden.
  useLayoutEffect(clearCelebrationMarker, []);
  useEffect(() => {
    if (!seen) haptic("success");
    // Storage remembers longer than a cookie set from a page may: write the cookie again when it lapsed.
    else if (!celebrationCookieSet(engagementId)) rememberCelebrationCookie(engagementId);
  }, [seen, engagementId]);
  if (seen) return null;
  return (
    <>
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
    </>
  );
}
