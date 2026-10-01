"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";

import { resetTour, type TourSide } from "./tour-store";

/** Help's "Show the tour again": forgets that this side's tour was seen, so it shows on the next visit to the person's home. */
export function ShowTourAgain({ side }: { side: TourSide }) {
  const t = useStrings("tour");
  const [done, setDone] = useState(false);
  const status = useRef<HTMLParagraphElement>(null);
  // The button goes when pressed: focus moves to the answer in its place, never to <body> (a keyboard user's next
  // Tab would otherwise leave the page).
  useEffect(() => {
    if (done) status.current?.focus();
  }, [done]);
  return (
    <div className="flex max-w-[65ch] flex-col items-start gap-3">
      <p className="text-ink">{t("showAgainLead")}</p>
      {done ? (
        <p ref={status} role="status" tabIndex={-1} className="text-ink focus:outline-none">
          {t("showAgainDone")}
        </p>
      ) : (
        <Button
          variant="secondary"
          onClick={() => {
            resetTour(side);
            setDone(true);
          }}
        >
          {t("showAgain")}
        </Button>
      )}
    </div>
  );
}
