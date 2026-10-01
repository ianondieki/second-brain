import { cn } from "@/components/ui/cn";

/**
 * The Wazo mark (direction C, D-52): a seal ring with one tick, on the accent. Decorative wherever the wordmark or a
 * text label is beside it.
 */
export function LogoMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false" className={cn("shrink-0", className)}>
      <circle cx="16" cy="16" r="13" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="10" fill="none" stroke="var(--flourish)" strokeWidth="1" />
      <path d="m10.5 16.5 3.6 3.5 7.4-8" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The mark and the name "Wazo" in the display face: the product's signature on every top bar, sheet and email. */
export function Wordmark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)} data-wordmark="">
      <LogoMark size={size} />
      <span className="font-display leading-none font-medium tracking-[-0.01em] text-ink" style={{ fontSize: size * 0.86 }}>
        Wazo
      </span>
    </span>
  );
}
