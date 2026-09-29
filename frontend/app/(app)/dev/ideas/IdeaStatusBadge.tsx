import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon, ClockIcon, EyeOffIcon, PencilIcon } from "@/components/ui/icons";

import type { IdeaStatus } from "./status";

const LOOK: Record<IdeaStatus, { Icon: ComponentType<SVGProps<SVGSVGElement>>; tone: string }> = {
  draft: { Icon: PencilIcon, tone: "text-ink-soft" },
  published: { Icon: CheckIcon, tone: "text-ok" },
  held: { Icon: ClockIcon, tone: "text-jacaranda" },
  rejected: { Icon: AlertIcon, tone: "text-error" },
  hidden: { Icon: EyeOffIcon, tone: "text-ink-soft" },
};

/** An idea's status as icon + words + colour (docs/spec/07 item 6), never colour alone. */
export function IdeaStatusBadge({ status, className }: { status: IdeaStatus; className?: string }) {
  const t = useTranslations("ideaFields");
  const { Icon, tone } = LOOK[status];
  return (
    <span data-status={status} className={cn("inline-flex items-center gap-1.5 font-medium", tone, className)}>
      <Icon className="size-5 shrink-0" />
      <span>{t(`status.${status}`)}</span>
    </span>
  );
}
