import { getTranslations } from "next-intl/server";

import { cn } from "./ui/cn";
import { InfoIcon } from "./ui/status-icons";

/**
 * Which sentence the line says (REQ-FND-04; ux review of P28-PD): `locked` where the whole feature is unavailable in
 * the demo (the calendar feed, uploads, a staff create form); `change` under a setting whose state still holds (the
 * persona's two-step sign-in is on, but changing it is off), so the line never reads as the setting's state; `decide`
 * in a staff decision region (the case or card still reads; deciding it does not).
 */
export type DemoLockedVariant = "locked" | "change" | "decide";

const KEY = { locked: "locked", change: "changeLocked", decide: "decideLocked" } as const satisfies Record<DemoLockedVariant, string>;

/**
 * One calm line where a control switched off in the public demo would be (REQ-FND-04; docs/platform/tasks/P28.md,
 * track PD): "Switched off in the public demo." by default, the variant's sentence, or the given sentence where the
 * line needs its own subject (the message composer's files). Server-rendered, no script; the API refuses the same
 * routes (403 public_demo_locked).
 */
export async function DemoLocked({
  sentence,
  variant = "locked",
  className,
}: {
  sentence?: string;
  variant?: DemoLockedVariant;
  className?: string;
}) {
  const text = sentence ?? (await getTranslations("publicDemo"))(KEY[variant]);
  return (
    <p className={cn("flex max-w-[65ch] items-start gap-2 text-ink", className)} data-demo-locked={variant}>
      <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />
      <span>{text}</span>
    </p>
  );
}
