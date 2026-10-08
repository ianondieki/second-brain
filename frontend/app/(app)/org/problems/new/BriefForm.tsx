"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Card, cardHeadingClass } from "@/components/ui/Card";
import { cn } from "@/components/ui/cn";
import { Form, SubmitButton } from "@/components/ui/Form";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { SelectField } from "@/components/ui/SelectField";
import { InfoIcon } from "@/components/ui/status-icons";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";
import { upgradeHref } from "@/lib/billing/upgrade";

import {
  BRIEF_LIMITS,
  bodyOf,
  charCount,
  checkBrief,
  DRAFT_FIELDS,
  EMPTY_DRAFT,
  MAX_STATEMENT_WORDS,
  wordCount,
  type BriefDraft,
  type BudgetBand,
  type DraftErrors,
  type DraftField,
  type FieldIssue,
  type Refused,
} from "../../brief-draft";
import { briefCalls, type BriefCalls } from "../calls";
import { BriefPreview } from "./BriefPreview";

export interface NicheGroup {
  id: string;
  name: string;
  children: { id: string; name: string }[];
}

export interface BriefFormProps {
  orgId: string;
  orgName: string;
  niches: NicheGroup[];
  counties: { id: string; label: string }[];
  bands: BudgetBand[];
  /** Today in Nairobi ("YYYY-MM-DD"): the earliest deadline. */
  today: string;
  /** The plan's open Briefs (null: unlimited), for the 402 sentence when the API leaves it out. */
  planLimit: number | null;
  /** Plan names by code, so a 402 names the next plan up in words. */
  planNames: Record<string, string>;
  /** Where a posted Brief goes: the list, with the "posted" note. */
  doneHref: string;
  /** This screen, for the checkout's way back after an upgrade. */
  hereHref: string;
  cancelHref: string;
  calls?: BriefCalls;
  /** The page's language, for the preview's date. */
  locale?: string;
}

const LIMIT: Partial<Record<DraftField, number>> = {
  title: BRIEF_LIMITS.title,
  statement: BRIEF_LIMITS.statement,
  affected: BRIEF_LIMITS.affected,
};

/**
 * "Post a brief" (REQ-DIR-05; docs/spec/06 6.2 last bullet): the problem in the ProblemCard's words (title, statement
 * with its meter, who is affected), where it fits (niche, county), and the budget band and deadline developers see.
 * Checked before sending; the API checks again (contact details, the lists, the plan) and each refusal is worded here:
 * a 402 names the next plan up with its checkout, a 403 the verification or the role, a 422 the fields. "Post the
 * brief" is the screen's one primary action; a posted Brief opens the list, newest first. Beside the form from 1024 px
 * (under its sections on a phone), a live preview of how the Brief reads on Discover (BriefPreview).
 */
export function BriefForm(props: BriefFormProps) {
  const t = useStrings("briefForm");
  const router = useRouter();
  const calls = props.calls ?? briefCalls;
  const [draft, setDraft] = useState<BriefDraft>(EMPTY_DRAFT);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<Refused | null>(null);
  const notice = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // A refusal about the whole Brief takes focus; one about its fields leaves focus on the first marked field.
    if (refused && refused.fields.length === 0) notice.current?.focus();
  }, [refused]);

  function change<K extends keyof BriefDraft>(field: K, value: BriefDraft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
    if (errors[field]) setErrors((current) => ({ ...current, [field]: undefined }));
    if (issues.some((issue) => issue.field === field)) setIssues((current) => current.filter((issue) => issue.field !== field));
  }

  function focusFirst(fields: readonly DraftField[]) {
    const first = DRAFT_FIELDS.find((field) => fields.includes(field));
    if (!first) return;
    const target = document.getElementById(`brief-${first}`);
    // A fieldset of radios takes no focus itself: its chosen radio does (or its first one).
    const radio = target?.tagName === "FIELDSET" ? (target.querySelector<HTMLInputElement>("input:checked") ?? target.querySelector("input")) : null;
    (radio ?? target)?.focus();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found = checkBrief(draft, props.today);
    setErrors(found);
    setIssues([]);
    const marked = DRAFT_FIELDS.filter((field) => found[field]);
    if (marked.length > 0) {
      setRefused(null);
      focusFirst(marked);
      return;
    }
    setBusy(true);
    setRefused(null);
    const outcome = await calls.create(props.orgId, bodyOf(draft));
    if (outcome.ok) {
      router.push(props.doneHref); // stays busy until the list replaces this screen
      return;
    }
    setBusy(false);
    setIssues(outcome.fields);
    setRefused(outcome);
    if (outcome.fields.length > 0) focusFirst(outcome.fields.map((issue) => issue.field));
  }

  /** A field's words: the form's own check first, else the API's code for it. */
  function errorFor(field: DraftField): string | undefined {
    const problem = errors[field];
    if (problem) return t(`error.${problem}`, { max: problem === "tooManyWords" ? MAX_STATEMENT_WORDS : (LIMIT[field] ?? 0) });
    const issue = issues.find((item) => item.field === field);
    if (!issue) return undefined;
    // The API's too_long for a statement within its characters is about its words.
    if (issue.code === "too_long" && field === "statement" && chars <= BRIEF_LIMITS.statement) {
      return t("error.tooManyWords", { max: MAX_STATEMENT_WORDS });
    }
    return t(`fieldError.${issue.code}`, { max: LIMIT[field] ?? 0 });
  }

  const words = wordCount(draft.statement);
  const chars = charCount(draft.statement);
  const over = chars > BRIEF_LIMITS.statement || words > MAX_STATEMENT_WORDS;
  const upgrade = refused?.refusal === "planLimit" ? refused.upgradePlan : null;

  return (
    <Form onSubmit={submit} className="brief-layout" aria-busy={busy || undefined} data-brief-form="">
      <div className="brief-fields flex flex-col gap-8">
      <Card as="section" variant="flat" aria-labelledby="brief-group-problem" className="flex flex-col gap-6">
        <h2 id="brief-group-problem" className={cardHeadingClass}>
          {t("group.problem")}
        </h2>
        <TextField
          id="brief-title"
          label={t("title")}
          hint={t("titleHint", { max: BRIEF_LIMITS.title })}
          value={draft.title}
          error={errorFor("title")}
          autoComplete="off"
          onChange={(e) => change("title", e.target.value)}
        />
        <TextAreaField
          id="brief-statement"
          label={t("statement")}
          hint={t("statementHint")}
          value={draft.statement}
          error={errorFor("statement")}
          rows={6}
          meter={
            <span className={cn(over && "font-semibold text-error")} data-meter="">
              {t("meter", { count: words, max: MAX_STATEMENT_WORDS, current: chars, limit: BRIEF_LIMITS.statement })}
            </span>
          }
          onChange={(e) => change("statement", e.target.value)}
        />
        <TextField
          id="brief-affected"
          label={t("affected")}
          hint={t("affectedHint")}
          value={draft.affected}
          error={errorFor("affected")}
          autoComplete="off"
          onChange={(e) => change("affected", e.target.value)}
        />
      </Card>

      <Card as="section" variant="flat" aria-labelledby="brief-group-fit" className="flex flex-col gap-6">
        <h2 id="brief-group-fit" className={cardHeadingClass}>
          {t("group.fit")}
        </h2>
        <div className="grid gap-6 sm:grid-cols-2">
          <SelectField
            id="brief-niche"
            label={t("niche")}
            value={draft.niche}
            error={errorFor("niche")}
            onChange={(e) => change("niche", e.target.value)}
          >
            <option value="">{t("nicheChoose")}</option>
            {props.niches.map((parent) =>
              parent.children.length > 0 ? (
                <optgroup key={parent.id} label={parent.name}>
                  <option value={parent.id}>{t("nicheAllIn", { name: parent.name })}</option>
                  {parent.children.map((child) => (
                    <option key={child.id} value={child.id}>
                      {child.name}
                    </option>
                  ))}
                </optgroup>
              ) : (
                <option key={parent.id} value={parent.id}>
                  {parent.name}
                </option>
              ),
            )}
          </SelectField>
          <SelectField
            id="brief-county"
            label={t("county")}
            value={draft.county}
            error={errorFor("county")}
            onChange={(e) => change("county", e.target.value)}
          >
            <option value="">{t("countyAny")}</option>
            {props.counties.map((county) => (
              <option key={county.id} value={county.id}>
                {county.label}
              </option>
            ))}
          </SelectField>
        </div>
      </Card>

      <Card as="section" variant="flat" aria-labelledby="brief-group-terms" className="flex flex-col gap-6">
        <h2 id="brief-group-terms" className={cardHeadingClass}>
          {t("group.terms")}
        </h2>
        <RadioGroup
          id="brief-band"
          name="budget_band"
          legend={t("band")}
          value={draft.band}
          error={errorFor("band")}
          onChange={(value) => change("band", value)}
          options={[
            ...props.bands.map((band) => ({ value: band.code, label: band.label })),
            { value: "", label: t("bandNone"), hint: t("bandNoneHint") },
          ]}
        />
        <TextField
          id="brief-deadline"
          type="date"
          label={t("deadline")}
          hint={t("deadlineHint")}
          min={props.today}
          value={draft.deadline}
          error={errorFor("deadline")}
          className="max-w-[14rem]"
          onChange={(e) => change("deadline", e.target.value)}
        />
      </Card>

      {/* Quiet, not a notice: what every Brief is today, and what comes later. */}
      <p className="-mt-2 flex max-w-[62ch] items-start gap-2 text-sm text-ink-soft" data-invited-note="">
        <InfoIcon className="mt-0.5 size-4 shrink-0" />
        <span>{t("invitedNote")}</span>
      </p>
      </div>

      <div className="brief-aside">
        <BriefPreview
          draft={draft}
          orgName={props.orgName}
          niches={props.niches}
          counties={props.counties}
          bands={props.bands}
          locale={props.locale ?? "en"}
        />
      </div>

      <div className="brief-submit flex flex-col gap-6">

      {refused ? (
        <Alert ref={notice} className="w-full" tone="error">
          <p data-refusal={refused.refusal}>{refusalText(t, refused, props)}</p>
          {upgrade ? (
            <Link href={upgradeHref(upgrade, { org: props.orgId, next: props.hereHref })} className={standaloneLinkClass} data-upgrade="">
              {t("upgrade")}
            </Link>
          ) : null}
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
        <SubmitButton variant="primary" busy={busy}>
          {busy ? t("posting") : t("submit")}
        </SubmitButton>
        <Link href={props.cancelHref} className={cn(standaloneLinkClass, "self-start sm:self-auto")}>
          {t("cancel")}
        </Link>
      </div>
      </div>
    </Form>
  );
}

/** A refusal in words: a 402 with its limit and the next plan's name (or none at the top of the ladder). */
function refusalText(t: ReturnType<typeof useStrings<"briefForm">>, refused: Refused, props: BriefFormProps): string {
  if (refused.refusal === "planLimit") {
    const limit = refused.limit ?? props.planLimit ?? 0;
    const plan = refused.upgradePlan ? (props.planNames[refused.upgradePlan] ?? null) : null;
    if (plan) return t("refusal.planLimit", { limit, plan });
    return t(refused.upgradePlan ? "refusal.planLimitNext" : "refusal.planLimitTop", { limit });
  }
  return t(`refusal.${refused.refusal}`, { org: props.orgName });
}
