import { getTranslations } from "next-intl/server";

import { cn } from "./ui/cn";
import { InfoIcon } from "./ui/status-icons";

/**
 * One calm line where a control switched off in the public demo would be (REQ-FND-04; docs/platform/tasks/P28.md,
 * track PD): "Switched off in the public demo." by default, or the given sentence where the line needs its subject
 * (the message composer's files). Server-rendered, no script; the API refuses the same routes (403 public_demo_locked).
 */
export async function DemoLocked({ sentence, className }: { sentence?: string; className?: string }) {
  const text = sentence ?? (await getTranslations("publicDemo"))("locked");
  return (
    <p className={cn("flex max-w-[65ch] items-start gap-2 text-ink", className)} data-demo-locked="">
      <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />
      <span>{text}</span>
    </p>
  );
}
