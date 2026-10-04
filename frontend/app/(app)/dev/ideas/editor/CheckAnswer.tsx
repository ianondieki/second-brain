import { Badge } from "@/components/ui/Badge";
import { PencilIcon } from "@/components/ui/icons";
import { AlertIcon, CheckIcon, InfoIcon } from "@/components/ui/status-icons";

// One answer of the editor's teaser checks (REQ-PROP-04, REQ-REPO-01), already worded. No hooks and no "use client":
// the editor's page draws today's last overlap check with it on the server (no script for it on the page), and the
// checks card draws every new answer with it in the browser, so both look the same.

export type AnswerTone = "clear" | "note" | "problem";

export interface CheckAnswerProps {
  /** clear: nothing to look at; note: worth a look (never a judgement); problem: the check did not answer. */
  tone: AnswerTone;
  sentence: string;
  /** A second, quieter sentence: the explainer, or why the teaser reads like how it works. */
  detail?: string | null;
  /** The AI labels (docs/spec/09), drawn as the writing assistant draws them: at most two. */
  chips?: Array<{ label: string; quiet?: boolean }>;
  /** A caption under it all ("From your last check today."). */
  caption?: string;
}

const ICON = { clear: CheckIcon, note: InfoIcon, problem: AlertIcon };
const ICON_TONE = { clear: "text-ok", note: "text-ink-soft", problem: "text-error" };

export function CheckAnswer({ tone, sentence, detail, chips = [], caption }: CheckAnswerProps) {
  const Icon = ICON[tone];
  return (
    <div data-check-answer={tone} className="flex max-w-[62ch] flex-col gap-1.5 [overflow-wrap:anywhere]">
      <p className="flex gap-2 text-ink">
        <Icon className={`mt-0.5 size-5 shrink-0 ${ICON_TONE[tone]}`} />
        <span>{sentence}</span>
      </p>
      {detail ? <p className="pl-7 text-sm text-ink-soft">{detail}</p> : null}
      {chips.length > 0 || caption ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-7">
          {chips.map(({ label, quiet }) => (
            <Badge key={label} data-chip="" tone="neutral" icon={quiet ? <InfoIcon /> : <PencilIcon />}>
              {label}
            </Badge>
          ))}
          {caption ? <span className="text-sm text-ink-soft">{caption}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
