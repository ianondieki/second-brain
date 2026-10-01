"use client";

import { useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";

import { resetTour } from "./tour-store";

/** Help's "Show the tour again": forgets that the tour was seen, so it shows on the next visit to the person's home. */
export function ShowTourAgain() {
  const t = useStrings("tour");
  const [done, setDone] = useState(false);
  return (
    <div className="flex max-w-[65ch] flex-col items-start gap-3">
      <p className="text-ink">{t("showAgainLead")}</p>
      {done ? (
        <p role="status" className="text-ink">
          {t("showAgainDone")}
        </p>
      ) : (
        <Button
          variant="secondary"
          onClick={() => {
            resetTour();
            setDone(true);
          }}
        >
          {t("showAgain")}
        </Button>
      )}
    </div>
  );
}
