import type { DirectionKey } from "../directions";

/** One empty-state illustration per direction, inline SVG on the tokens (decorative). About 2 KB each. */
export function EmptyIllustration({ direction }: { direction: DirectionKey }) {
  const common = { viewBox: "0 0 240 120", width: 240, height: 120, "aria-hidden": true, focusable: false, className: "mx-auto block" } as const;
  if (direction === "a") {
    return (
      <svg {...common}>
        <defs>
          <pattern id="lab-grid" width="12" height="12" patternUnits="userSpaceOnUse">
            <path d="M12 0H0v12" fill="none" stroke="var(--line)" strokeWidth="0.6" />
          </pattern>
        </defs>
        <rect width="240" height="120" fill="url(#lab-grid)" />
        <g fill="none" stroke="var(--ink)" strokeWidth="1.4" strokeLinejoin="round">
          <path d="m40 70 30-17 30 17-30 17z" />
          <path d="M40 70v14l30 17v-14M100 70v14l-30 17" />
          <path d="m140 50 30-17 30 17-30 17z" stroke="var(--jacaranda)" strokeWidth="1.8" />
          <path d="M140 50v14l30 17v-14M200 50v14l-30 17" stroke="var(--jacaranda)" strokeWidth="1.8" />
        </g>
        <path d="M100 70 140 55" stroke="var(--jacaranda)" strokeWidth="1.8" strokeDasharray="4 4" />
      </svg>
    );
  }
  if (direction === "b") {
    return (
      <svg {...common}>
        <path d="M30 100c20-50 60-70 90-70s70 20 90 70Z" fill="var(--jacaranda-wash)" />
        <path d="M70 100c10-30 30-45 50-45s40 15 50 45Z" fill="var(--flourish)" opacity="0.55" />
        <path d="M100 100c5-15 12-22 20-22s15 7 20 22Z" fill="var(--jacaranda)" />
        <path d="M20 100h200" stroke="var(--line)" strokeWidth="2" strokeLinecap="round" />
        <path d="M150 38h12l-6-10zM166 38h12l-6-10zM182 38h12l-6-10z" fill="var(--flourish)" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <g fill="none" stroke="var(--ink)" strokeWidth="1" strokeLinecap="round">
        <path d="M50 92h140M60 92c0-40 25-62 60-62s60 22 60 62" />
        <path d="M80 92c0-22 15-40 40-40s40 18 40 40M100 92c0-10 8-18 20-18s20 8 20 18" />
        <path d="M120 30v62" strokeDasharray="1 5" />
      </g>
      <path d="M48 92c30-6 60-8 72-8s42 2 72 8" fill="none" stroke="var(--jacaranda)" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="48" cy="92" r="3" fill="var(--jacaranda)" />
      <circle cx="192" cy="92" r="3" fill="none" stroke="var(--jacaranda)" strokeWidth="1.8" />
    </svg>
  );
}
