import { BriefIcon, CalendarIcon } from "@/components/org-icons";
import { EngagementsIcon, MessageIcon } from "@/components/tracker/icons";
import { Icon, type IconProps } from "@/components/ui/status-icons";

import type { DeadlineKind } from "./month";

/** A milestone: a diamond on its line, a point reached in the agreement's plan. */
function MilestoneIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 3.75 16.25 10 10 16.25 3.75 10z" />
      <path d="M10 7.75 12.25 10 10 12.25 7.75 10z" />
    </Icon>
  );
}

/**
 * What a deadline is, as a mark beside its words (never alone: the kind's name or the row's text says it): the
 * engagement's stage (the Engagements arrows), the answer to a question (a speech bubble), a milestone (a diamond),
 * a Brief (its page), an event (a calendar page). Decorative, the outline set's stroke.
 */
export function KindMark({ kind, className }: { kind: DeadlineKind; className?: string }) {
  const Mark = {
    stage: EngagementsIcon,
    answer: MessageIcon,
    milestone: MilestoneIcon,
    brief: BriefIcon,
    event: CalendarIcon,
  }[kind];
  return <Mark className={className} data-kind-mark={kind} />;
}
