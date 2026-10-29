import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { AlertIcon, CheckIcon, ClockIcon, EyeOffIcon, PencilIcon } from "@/components/ui/icons";

import type { IdeaStatus } from "./status";

// Published in the success tone, not approved in the error tone, the rest neutral: the accent stays for "act here"
// (docs/platform/design/p16-design-system.md, principle 3).
const LOOK: Record<IdeaStatus, { Icon: ComponentType<SVGProps<SVGSVGElement>>; tone: BadgeTone }> = {
  draft: { Icon: PencilIcon, tone: "neutral" },
  published: { Icon: CheckIcon, tone: "ok" },
  held: { Icon: ClockIcon, tone: "neutral" },
  rejected: { Icon: AlertIcon, tone: "error" },
  hidden: { Icon: EyeOffIcon, tone: "neutral" },
};

/** An idea's status, a Badge: icon + words + tone (docs/spec/07 item 6), never colour alone. */
export function IdeaStatusBadge({ status, className }: { status: IdeaStatus; className?: string }) {
  const t = useTranslations("ideaFields");
  const { Icon, tone } = LOOK[status];
  return (
    <Badge data-status={status} tone={tone} icon={<Icon />} className={className}>
      {t(`status.${status}`)}
    </Badge>
  );
}
