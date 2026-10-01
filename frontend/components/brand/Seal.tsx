import { cn } from "@/components/ui/cn";

/**
 * The authorship seal: the mark's ring at sheet size, with the words "Wazo · Registered" around it and the tick. The
 * outer ring draws once (seal-draw); decorative, the sheet's text says what it certifies.
 */
export function Seal({ size = 112, animate = false, className }: { size?: number; animate?: boolean; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 112 112" aria-hidden="true" focusable="false" className={cn("shrink-0", className)} data-seal="">
      <defs>
        <path id="seal-text-path" d="M56 12a44 44 0 1 1-.01 0" fill="none" />
      </defs>
      <circle cx="56" cy="56" r="52" fill="var(--field)" stroke="var(--accent)" strokeWidth="1.5" pathLength={100} className={animate ? "seal-draw" : undefined} />
      <circle cx="56" cy="56" r="34" fill="none" stroke="var(--flourish)" strokeWidth="1" />
      <text fontSize="9" fontWeight="600" fill="var(--accent)" fontFamily="var(--font-sans)" textLength="274" lengthAdjust="spacing">
        <textPath href="#seal-text-path" startOffset="0" textLength="274" lengthAdjust="spacing">
          WAZO · REGISTERED · WAZO · REGISTERED ·
        </textPath>
      </text>
      <path d="m42 57 9 9 19-21" fill="none" stroke="var(--accent)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
