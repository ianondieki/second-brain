import { cn } from "@/components/ui/cn";

/**
 * The Wazo mark (D-55): a bloom tile with a white "W" drawn as the kanga lattice's teeth, and a saffron spark over its
 * middle peak (wazo: an idea). Colours come from the tokens, so dark mode redraws it. Decorative wherever the wordmark
 * or a text label is beside it.
 */
export function LogoMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false" className={cn("shrink-0", className)}>
      <rect x="1" y="1" width="30" height="30" rx="9" fill="var(--accent)" />
      <path
        d="M7.5 11.5 11.75 22.5 16 14.5l4.25 8 4.25-11"
        fill="none"
        stroke="var(--on-accent)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="8.25" r="2.25" fill="var(--flourish)" />
    </svg>
  );
}

/** The mark and the name "Wazo" in the figure face (Bricolage; D-66): the product's signature on every top bar, sheet and email. */
export function Wordmark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)} data-wordmark="">
      <LogoMark size={size} />
      <span className="font-figure leading-none font-[760] tracking-[-0.035em] text-ink" style={{ fontSize: size * 0.92 }}>
        Wazo
      </span>
    </span>
  );
}
