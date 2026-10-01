"use client";

import { useStrings } from "@/components/ClientStrings";

import { Callout } from "@/components/ui/Callout";
import { Card } from "@/components/ui/Card";
import { LockIcon } from "@/components/ui/status-icons";
import { TextAreaField } from "@/components/ui/TextAreaField";

import { LIMITS, linksProblem, type Attachment, type EditorState } from "../ideas";
import type { Calls } from "../calls";
import { Attachments, type AttachmentsProps } from "./Attachments";
import { useIssueMessage } from "./issues";

export interface DetailsStepProps {
  state: EditorState;
  update: (patch: Partial<EditorState>) => void;
  attachments: Attachment[];
  onAttachments: AttachmentsProps["onAttachments"];
  ensureDraft: AttachmentsProps["ensureDraft"];
  getCalls: () => Promise<Calls>;
}

const WRITTEN = ["approach", "architecture", "pricing", "notes"] as const;

/**
 * Step 2, Full details (Tier 2): marked confidential with who can read it, in the approved wording (docs/spec/04 4.2).
 * Loaded when the step opens.
 */
export function DetailsStep({ state, update, ...files }: DetailsStepProps) {
  const t = useStrings("ideaEditor");
  const f = useStrings("ideaFields");
  const issueMessage = useIssueMessage();
  const linkProblem = linksProblem(state.links);
  return (
    <Card as="section" variant="flat" aria-labelledby="details-notice" className="flex flex-col gap-6">
      {/* Who can read this step, as a static notice with a lock (no coloured left rule). */}
      <Callout
        tone="neutral"
        titleId="details-notice"
        title={f("confidentialBadge")}
        icon={<LockIcon className="mt-0.5 size-5 shrink-0 text-ink-soft" />}
      >
        <p className="max-w-[62ch] text-sm text-ink-soft">{f("confidentialNotice")}</p>
      </Callout>
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
      <Attachments {...files} />
    </Card>
  );
}
