"use client";

import { useEffect, useRef, useState } from "react";

import { PauseIcon, PlayIcon } from "@/components/icons/lucide";

/**
 * Pause and play for a moving row (the county strip, the activity ticker; WCAG 2.2.2): a 44 px button, pressed while
 * paused, that marks its `[data-motion]` box `data-paused` (globals.css holds the row still). For the strip it also
 * brings a focused tile fully into view: focus inside the box turns the row static and scrollable (CSS), and the tile
 * is scrolled to once that has applied. Hidden under reduced motion, where nothing moves.
 */
export function MotionToggle({ label }: { label: string }) {
  const [paused, setPaused] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const box = ref.current?.closest<HTMLElement>("[data-motion]");
    if (!box) return;
    box.toggleAttribute("data-paused", paused);
  }, [paused]);
  useEffect(() => {
    const box = ref.current?.closest<HTMLElement>("[data-motion]");
    const reveal = (event: FocusEvent) => {
      const target = event.target as HTMLElement;
      if (target !== ref.current) requestAnimationFrame(() => target.scrollIntoView({ block: "nearest", inline: "nearest" }));
    };
    box?.addEventListener("focusin", reveal);
    return () => box?.removeEventListener("focusin", reveal);
  }, []);
  return (
    <button ref={ref} type="button" className="tour-pause motion-toggle" aria-label={label} aria-pressed={paused} title={label} onClick={() => setPaused(!paused)}>
      {paused ? <PlayIcon /> : <PauseIcon />}
    </button>
  );
}
