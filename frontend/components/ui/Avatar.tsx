import { cn } from "./cn";

/** The initials an avatar shows: the first letters of the first two words ("Achieng Otieno" → "AO"; "Telco A (fixture)" → "TA"). */
export function initialsOf(name: string): string {
  const words = name.replace(/\(.*?\)/g, " ").trim().split(/\s+/).filter(Boolean);
  const letters = words.slice(0, 2).map((w) => w[0]!.toUpperCase());
  return letters.join("") || "?";
}

export interface AvatarProps {
  name: string;
  /** Named for tests and styling hooks; both kinds are round (one avatar shape everywhere). */
  kind?: "person" | "org";
  size?: "sm" | "md" | "lg";
  /** Marks the party whose turn it is. */
  active?: boolean;
  /** Decorative when the name is written next to it (the default); otherwise the name is the accessible label. */
  labelled?: boolean;
  className?: string;
}

const SIZES = { sm: "size-7 text-xs", md: "size-9 text-sm", lg: "size-12 text-base" } as const;

/** An avatar with initials (no photos in the prototype): round, accent on the wash, a ring when it is this party's turn. */
export function Avatar({ name, kind = "person", size = "md", active = false, labelled = false, className }: AvatarProps) {
  return (
    <span
      data-avatar={kind}
      role={labelled ? "img" : undefined}
      aria-label={labelled ? name : undefined}
      aria-hidden={labelled ? undefined : true}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-accent-wash font-semibold text-accent tabular-nums select-none",
        active && "ring-2 ring-accent ring-offset-2 ring-offset-paper",
        SIZES[size],
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}
