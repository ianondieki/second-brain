import { cn } from "@/components/ui/cn";

import type { QuestionOutcome } from "./quiz";

const TONE: Record<QuestionOutcome | "open" | "done", string> = {
  right: "bg-accent",
  done: "bg-accent",
  wrong: "bg-ink-soft/40",
  skipped: "border border-dashed border-ink-soft",
  pulled: "border border-line",
  open: "bg-line",
};

/**
 * Today's five as five short bars (decorative: the words beside them carry the score or the progress). A finished
 * question is bloom when right, muted when wrong, dashed when skipped, an outline when withdrawn; on the play form a
 * bar fills as its question is answered (180 ms, still under reduced motion).
 */
export function Marks({ marks, className }: { marks: ReadonlyArray<QuestionOutcome | "open" | "done">; className?: string }) {
  return (
    <span aria-hidden="true" className={cn("flex gap-1", className)}>
      {marks.map((mark, index) => (
        <span
          key={index}
          className={cn("h-1.5 w-6 rounded-full transition-colors duration-180 motion-reduce:transition-none", TONE[mark])}
        />
      ))}
    </span>
  );
}
