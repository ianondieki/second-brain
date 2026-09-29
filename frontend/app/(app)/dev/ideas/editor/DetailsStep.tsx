"use client";

import { useTranslations } from "next-intl";

import { LockIcon } from "@/components/ui/icons";
import { TextAreaField } from "@/components/ui/TextAreaField";

import { LIMITS, linksProblem, type Attachment, type EditorState } from "../ideas";
import { Attachments } from "./Attachments";
import { useIssueMessage } from "./issues";

export interface DetailsStepProps {
  state: EditorState;
  update: (patch: Partial<EditorState>) => void;
  attachments: Attachment[];
  onAttachments: (attachments: Attachment[]) => void;
  ensureId: () => Promise<string | null>;
}

const WRITTEN = ["approach", "architecture", "pricing", "notes"] as const;

/**
 * Step 2, Full details (Tier 2): marked confidential with who can read it, in the approved wording (docs/spec/04 4.2).
 * Loaded when the step opens.
 */
export function DetailsStep({ state, update, attachments, onAttachments, ensureId }: DetailsStepProps) {
  const t = useTranslations("ideaEditor");
  const f = useTranslations("ideaFields");
  const issueMessage = useIssueMessage();
  const linkProblem = linksProblem(state.links);
  return (
    <section aria-labelledby="details-notice" className="flex flex-col gap-6 border-l-4 border-jacaranda pl-4 sm:pl-6">
      <div>
        <p id="details-notice" className="inline-flex items-center gap-1.5 font-semibold text-jacaranda">
          <LockIcon className="size-5 shrink-0" />
          {f("confidentialBadge")}
        </p>
        <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{f("confidentialNotice")}</p>
      </div>
      {WRITTEN.map((key) => (
        <TextAreaField
          key={key}
          id={`idea-${key}`}
          label={f(key)}
          hint={t(`${key}Hint`)}
          value={state[key]}
          maxLength={LIMITS[key]}
          rows={key === "approach" || key === "architecture" ? 6 : 4}
          onChange={(e) => update({ [key]: e.target.value })}
        />
      ))}
      <TextAreaField
        id="idea-links"
        label={f("links")}
        hint={t("linksHint")}
        value={state.links}
        rows={3}
        inputMode="url"
        spellCheck={false}
        autoCapitalize="none"
        error={linkProblem ? issueMessage({ field: "links", code: linkProblem }) : undefined}
        onChange={(e) => update({ links: e.target.value })}
      />
      <Attachments attachments={attachments} onChange={onAttachments} ensureId={ensureId} />
    </section>
  );
}
