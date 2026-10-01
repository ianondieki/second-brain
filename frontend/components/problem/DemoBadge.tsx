"use client";

import { useId, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { InfoIcon } from "@/components/ui/status-icons";

/**
 * The demo honesty label as a small muted badge (D-52): the full sentence ("Seeded example for the demo, not a live
 * AI result, human-reviewed on …") opens on press under it, and is always there for assistive technology.
 */
export function DemoBadge({ label, sentence, ...data }: { label: string; sentence: string; "data-label"?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2" {...data}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((was) => !was)}
        title={sentence}
        // A 44 px hit area around a small pill (negative margins keep the meta line's height).
        className="-my-2.5 inline-flex min-h-11 items-center text-ink-soft hover:text-ink"
      >
        <span className="inline-flex items-center rounded-full border border-line px-2 py-0.5 hover:border-accent-line">
          <Badge tone="neutral" icon={<InfoIcon />} className="text-xs">
            {label}
          </Badge>
        </span>
      </button>
      <span id={id} className={open ? "text-sm text-ink-soft" : "sr-only"}>
        {sentence}
      </span>
    </span>
  );
}
