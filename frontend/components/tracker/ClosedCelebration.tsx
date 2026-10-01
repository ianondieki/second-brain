"use client";

import { useEffect, useSyncExternalStore } from "react";

import { Seal } from "@/components/brand/Seal";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { CheckIcon } from "@/components/ui/status-icons";
import { haptic } from "@/lib/haptics";

const KEY_PREFIX = "wazo-closed:v1:";
const listeners = new Set<() => void>();

function key(id: string) {
  return KEY_PREFIX + id;
}

function read(id: string): boolean {
  try {
    return window.localStorage.getItem(key(id)) === "seen";
  } catch {
    return true; // storage off: never celebrate twice by accident, so not at all
  }
}

/** Marks the celebration as seen for this engagement; it never shows again on this device. */
export function dismissCelebration(id: string) {
  try {
    window.localStorage.setItem(key(id), "seen");
  } catch {
    // Storage off: the card closes for this render only.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export interface ClosedCelebrationProps {
  engagementId: string;
  title: string;
  body: string;
  dismiss: string;
}

/**
 * The one-time celebration of a closed engagement (D-52, feel): the seal draws its ring once, a few lattice-coloured
 * dots fall (still under reduced motion), a short buzz on phones, and one button to put it away. Shown the first time
 * this device opens a CLOSED tracker, then remembered; the stage chip and the timeline say "Closed" on every visit.
 */
export function ClosedCelebration({ engagementId, title, body, dismiss }: ClosedCelebrationProps) {
  const seen = useSyncExternalStore(subscribe, () => read(engagementId), () => true);
  useEffect(() => {
    if (!seen) haptic("success");
  }, [seen]);
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
            <Button variant="secondary" onClick={() => dismissCelebration(engagementId)}>
              {dismiss}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
