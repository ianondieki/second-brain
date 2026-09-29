import { cn } from "@/components/ui/cn";
import { CheckIcon, InfoIcon, ListedIcon } from "@/components/ui/icons";

import type { OrgCard } from "./filters";

const LOOK = {
  e2: { Icon: CheckIcon, tone: "text-ok" },
  e1: { Icon: InfoIcon, tone: "text-jacaranda" },
  e0: { Icon: ListedIcon, tone: "text-ink-soft" },
} as const;

/**
 * The verification badge: icon + words + colour (docs/spec/07 item 6). The words are the API's approved badge copy,
 * shown verbatim (docs/spec/06 6.2 for E0 and E1; the E2 text is D-31's placeholder until approved), never
 * rephrased here. E2 is a check, E1 an "i", and E0 an open dashed ring: listed, not verified.
 */
export function VerificationBadge({ badge, className }: { badge: OrgCard["badge"]; className?: string }) {
  const { Icon, tone } = LOOK[badge.level];
  return (
    <p data-badge={badge.level} className={cn("flex items-start gap-1.5 text-sm font-medium", tone, className)}>
      <Icon className="mt-px size-5 shrink-0" />
      <span>{badge.text}</span>
    </p>
  );
}
