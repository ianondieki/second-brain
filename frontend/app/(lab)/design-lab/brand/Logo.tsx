import type { DirectionKey } from "../directions";

/**
 * Logo marks, one per direction, as plain SVG on the direction's tokens; the wordmark is the name set in the
 * direction's display face next to it (docs/demo/directions/logo-*.svg are these marks as files).
 * A: two nodes joined by one bar (the bridge as a circuit). B: a kanga diamond cut by a span (the bridge as a
 * lattice). C: a seal ring with one tick (the bridge as a registry).
 */
export function LogoMark({ direction, size = 32, className }: { direction: DirectionKey; size?: number; className?: string }) {
  const common = { width: size, height: size, viewBox: "0 0 32 32", "aria-hidden": true, focusable: false, className } as const;
  if (direction === "a") {
    return (
      <svg {...common}>
        <rect x="2" y="2" width="28" height="28" rx="7" fill="var(--jacaranda)" />
        <rect x="8" y="17" width="7" height="7" rx="1.5" fill="var(--on-accent)" />
        <rect x="17" y="8" width="7" height="7" rx="1.5" fill="var(--on-accent)" opacity="0.55" />
        <path d="M11.5 17 20.5 15" stroke="var(--on-accent)" strokeWidth="2.4" strokeLinecap="round" />
      </svg>
    );
  }
  if (direction === "b") {
    return (
      <svg {...common}>
        <path d="M16 2 30 16 16 30 2 16Z" fill="var(--jacaranda)" />
        <path d="M16 8 24 16 16 24 8 16Z" fill="var(--flourish)" />
        <path d="M4 16h24" stroke="var(--paper)" strokeWidth="3" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="16" cy="16" r="13" fill="none" stroke="var(--jacaranda)" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="10" fill="none" stroke="var(--jacaranda)" strokeWidth="1" opacity="0.5" />
      <path d="m10.5 16.5 3.6 3.5 7.4-8" fill="none" stroke="var(--jacaranda)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The mark and the name together, in the direction's display face. */
export function Wordmark({ direction, name, size = 28 }: { direction: DirectionKey; name: string; size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5" data-wordmark={direction}>
      <LogoMark direction={direction} size={size} />
      <span
        className="leading-none text-ink"
        style={{
          fontFamily: "var(--font-display)",
          fontWeight: "var(--display-weight)" as unknown as number,
          letterSpacing: "var(--display-tracking)",
          fontSize: size * 0.86,
        }}
      >
        {name}
      </span>
    </span>
  );
}
