import { Badge, badgeBase, type BadgeTone } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import { CheckIcon, InfoIcon, ListedIcon } from "@/components/ui/icons";

import type { OrgCard } from "./filters";

// E2 in the success tone; E1 and E0 neutral, told apart by their marks and words (the accent is for "act here").
const LOOK = {
  e2: { Icon: CheckIcon, tone: "ok" },
  e1: { Icon: InfoIcon, tone: "neutral" },
  e0: { Icon: ListedIcon, tone: "neutral" },
} as const satisfies Record<string, { Icon: unknown; tone: BadgeTone }>;

/**
 * The verification badge, a Badge: icon + words + tone (docs/spec/07 item 6). The words are the API's approved badge
 * copy, shown verbatim (docs/spec/06 6.2 for E0 and E1; the E2 text is D-31's placeholder until approved), never
 * rephrased here. E2 is a check, E1 an "i", and E0 an open dashed ring: listed, not verified.
 */
export function VerificationBadge({ badge, className }: { badge: OrgCard["badge"]; className?: string }) {
  const { Icon, tone } = LOOK[badge.level];
  // E0's sentence is long ("Listed from public information · not on the platform · not affiliated"): as a pill it
  // wraps into a ragged box, so it is the same mark and words without the fill, quieter than a verified level (P20).
  if (badge.level === "e0") {
    return (
      <span data-badge="e0" className={cn(badgeBase, "font-medium text-ink-soft", className)}>
        <Icon />
        <span className="min-w-0">{badge.text}</span>
      </span>
    );
  }
  return (
    <Badge data-badge={badge.level} tone={tone} icon={<Icon />} className={className}>
      {badge.text}
    </Badge>
  );
}
