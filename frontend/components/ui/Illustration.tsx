import { cn } from "./cn";

export type IllustrationKind = "empty" | "waiting" | "done";

/**
 * Engraving-style line drawings for empty and quiet states (D-52): thin ink lines with one accent stroke, about 1 KB
 * each, drawn on the tokens so they follow dark mode. Decorative.
 */
export function Illustration({ kind = "empty", className }: { kind?: IllustrationKind; className?: string }) {
  const common = { viewBox: "0 0 240 100", "aria-hidden": true, focusable: false, className: cn("block h-auto w-full max-w-60", className), "data-illustration": kind } as const;
  if (kind === "waiting") {
    return (
      <svg {...common}>
        <g fill="none" stroke="var(--ink)" strokeWidth="1" strokeLinecap="round">
          <circle cx="120" cy="50" r="34" />
          <circle cx="120" cy="50" r="28" strokeDasharray="1 4" />
        </g>
        <path d="M120 50V30M120 50l14 10" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
        <path d="M20 86h200" stroke="var(--line)" strokeWidth="1" />
      </svg>
    );
  }
  if (kind === "done") {
    return (
      <svg {...common}>
        <g fill="none" stroke="var(--ink)" strokeWidth="1" strokeLinecap="round">
          <path d="M60 80c0-30 25-50 60-50s60 20 60 50" />
          <path d="M80 80c0-18 15-32 40-32s40 14 40 32" strokeDasharray="1 4" />
        </g>
        <path d="m104 58 10 10 22-24" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M20 86h200" stroke="var(--line)" strokeWidth="1" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <g fill="none" stroke="var(--ink)" strokeWidth="1" strokeLinecap="round">
        <path d="M50 84h140M60 84c0-36 25-58 60-58s60 22 60 58" />
        <path d="M80 84c0-20 15-38 40-38s40 18 40 38M100 84c0-10 8-18 20-18s20 8 20 18" />
        <path d="M120 26v58" strokeDasharray="1 5" />
      </g>
      <path d="M48 84c30-6 60-8 72-8s42 2 72 8" fill="none" stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="48" cy="84" r="3" fill="var(--accent)" />
      <circle cx="192" cy="84" r="3" fill="none" stroke="var(--accent)" strokeWidth="1.8" />
    </svg>
  );
}
