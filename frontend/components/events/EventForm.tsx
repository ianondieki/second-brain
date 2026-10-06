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
import { SelectField } from "@/components/ui/SelectField";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";

import {
  checkEvent,
  EMPTY_EVENT,
  EVENT_FIELDS,
  EVENT_LIMITS,
  eventBody,
  charCount,
  type EventDraft,
  type EventErrors,
  type EventField,
  type EventRefused,
  type FieldIssue,
} from "./event-draft";
import { eventCalls, type EventCalls, type EventPoster } from "./calls";

export interface EventFormProps {
  counties: { id: string; label: string }[];
  /** Who posts: the organisation's name, or the platform's word for staff (in the refusal sentences). */
  poster: string;
  /** Who posts it: the organisation (its POST) or the staff console (a platform event). */
  target: EventPoster;
  /** The new event's page is `${doneBase}/${id}${doneQuery}` (its header takes focus there). */
  doneBase: string;
  doneQuery?: string;
  cancelHref: string;
  calls?: EventCalls;
}

const LIMIT: Partial<Record<EventField, number>> = {
  title: EVENT_LIMITS.title,
  description: EVENT_LIMITS.description,
  venue: EVENT_LIMITS.venue,
};

const id = (field: EventField) => `event-${field}`;

/**
 * "Post an event" (REQ-DEV-02; D-60): what it is (title, description), when in Nairobi (start and end, each a date and
 * a time), where (a venue and its county, or online with the join address: the switch swaps them), and its own page.
 * Checked before sending; the API checks again and each refusal is worded here, a 422 under its field. "Post for
 * review" is the screen's one primary action; a posted event opens its own page, whose header takes focus.
 */
export function EventForm({ counties, poster, target, doneBase, doneQuery = "", cancelHref, calls: given }: EventFormProps) {
  const t = useStrings("eventForm");
  const router = useRouter();
  const calls = useRef(given ?? eventCalls()).current;
  const [draft, setDraft] = useState<EventDraft>(EMPTY_EVENT);
  const [errors, setErrors] = useState<EventErrors>({});
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<EventRefused | null>(null);
  const notice = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (refused && refused.fields.length === 0) notice.current?.focus();
  }, [refused]);

  function change<K extends keyof EventDraft>(field: K, value: EventDraft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
    if (field in errors) setErrors((current) => ({ ...current, [field]: undefined }));
    if (issues.some((issue) => issue.field === field)) setIssues((current) => current.filter((issue) => issue.field !== field));
  }

  function focusFirst(fields: readonly EventField[]) {
    const first = EVENT_FIELDS.find((field) => fields.includes(field));
    if (first) document.getElementById(id(first))?.focus();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found = checkEvent(draft);
    setErrors(found);
    setIssues([]);
    const marked = EVENT_FIELDS.filter((field) => found[field]);
    if (marked.length > 0) {
      setRefused(null);
      focusFirst(marked);
      return;
    }
    setBusy(true);
    setRefused(null);
    const outcome = await calls.post(target, eventBody(draft));
    if (outcome.ok) {
      router.push(`${doneBase}/${encodeURIComponent(outcome.value.id)}${doneQuery}`); // stays busy until the event's page replaces this screen
      return;
    }
    setBusy(false);
    setIssues(outcome.fields);
    setRefused(outcome);
    if (outcome.fields.length > 0) focusFirst(outcome.fields.map((issue) => issue.field));
  }

  /** A field's words: the form's own check first, else the API's code for it. */
  function errorFor(field: EventField): string | undefined {
    const code = errors[field] ?? issues.find((item) => item.field === field)?.code;
    return code ? t(`fieldError.${code}`, { max: LIMIT[field] ?? 0 }) : undefined;
  }

  const chars = charCount(draft.description);
  return (
    <Form onSubmit={submit} className="flex flex-col gap-8" aria-busy={busy || undefined} data-event-form="">
      <Card as="section" variant="flat" aria-labelledby="event-group-what" className="flex flex-col gap-6">
        <h2 id="event-group-what" className={cardHeadingClass}>
          {t("group.what")}
        </h2>
        <TextField
          id={id("title")}
          label={t("title")}
          hint={t("titleHint", { max: EVENT_LIMITS.title })}
          value={draft.title}
          error={errorFor("title")}
          autoComplete="off"
          onChange={(e) => change("title", e.target.value)}
        />
        <TextAreaField
          id={id("description")}
          label={t("description")}
          hint={t("descriptionHint")}
          value={draft.description}
          error={errorFor("description")}
          rows={6}
          meter={
            <span className={cn(chars > EVENT_LIMITS.description && "font-semibold text-error")}>
              {t("meter", { current: chars, max: EVENT_LIMITS.description })}
            </span>
          }
          onChange={(e) => change("description", e.target.value)}
        />
      </Card>

      <Card as="section" variant="flat" aria-labelledby="event-group-when" className="flex flex-col gap-6">
        <div>
          <h2 id="event-group-when" className={cardHeadingClass}>
            {t("group.when")}
          </h2>
          <p className="mt-1 text-sm text-ink-soft">{t("whenHint")}</p>
        </div>
        {(["start", "end"] as const).map((edge) => (
          <fieldset key={edge} className="grid grid-cols-2 gap-x-3 gap-y-4 sm:gap-x-4">
            <legend className="col-span-2 mb-2 font-semibold text-ink">{t(`${edge}s`)}</legend>
            <TextField
              id={id(`${edge}Date`)}
              type="date"
              label={t("date")}
              value={draft[`${edge}Date`]}
              error={errorFor(`${edge}Date`)}
              onChange={(e) => change(`${edge}Date`, e.target.value)}
            />
            <TextField
              id={id(`${edge}Time`)}
              type="time"
              label={t("time")}
              value={draft[`${edge}Time`]}
              error={errorFor(`${edge}Time`)}
              onChange={(e) => change(`${edge}Time`, e.target.value)}
            />
          </fieldset>
        ))}
      </Card>

      <Card as="section" variant="flat" aria-labelledby="event-group-where" className="flex flex-col gap-6">
        <h2 id="event-group-where" className={cardHeadingClass}>
          {t("group.where")}
        </h2>
        <div className="flex flex-col gap-1">
          <button
            type="button"
            role="switch"
            aria-checked={draft.online}
            aria-describedby="event-online-hint"
            onClick={() => change("online", !draft.online)}
            className="group inline-flex min-h-11 items-center gap-3 self-start font-semibold text-ink"
            data-online-switch=""
          >
            <span
              aria-hidden="true"
              className="relative h-6 w-10 shrink-0 rounded-full border border-ink-soft bg-field transition-colors group-aria-checked:border-accent group-aria-checked:bg-accent motion-reduce:transition-none"
            >
              <span className="absolute top-0.5 left-0.5 size-4 rounded-full bg-ink-soft transition-transform group-aria-checked:translate-x-4 group-aria-checked:bg-on-accent motion-reduce:transition-none" />
            </span>
            {t("online")}
          </button>
          <p id="event-online-hint" className="max-w-[60ch] text-sm text-ink-soft">
            {t("onlineHint")}
          </p>
        </div>
        {draft.online ? (
          <TextField
            id={id("joinUrl")}
            type="url"
            inputMode="url"
            label={t("joinUrl")}
            hint={t("joinUrlHint")}
            value={draft.joinUrl}
            error={errorFor("joinUrl")}
            autoComplete="off"
            onChange={(e) => change("joinUrl", e.target.value)}
          />
        ) : (
          <div className="grid gap-6 sm:grid-cols-2">
            <TextField
              id={id("venue")}
              label={t("venue")}
              hint={t("venueHint", { max: EVENT_LIMITS.venue })}
              value={draft.venue}
              error={errorFor("venue")}
              autoComplete="off"
              onChange={(e) => change("venue", e.target.value)}
            />
            <SelectField id={id("county")} label={t("county")} value={draft.county} error={errorFor("county")} onChange={(e) => change("county", e.target.value)}>
              <option value="">{t("countyChoose")}</option>
              {counties.map((county) => (
                <option key={county.id} value={county.id}>
                  {county.label}
                </option>
              ))}
            </SelectField>
          </div>
        )}
        <TextField
          id={id("link")}
          type="url"
          inputMode="url"
          label={t("link")}
          hint={t("linkHint")}
          value={draft.link}
          error={errorFor("link")}
          autoComplete="off"
          onChange={(e) => change("link", e.target.value)}
        />
      </Card>

      <p className="-mt-2 max-w-[62ch] text-sm text-ink-soft">{t("reviewNote")}</p>

      {refused ? (
        <Alert ref={notice} className="w-full" tone="error">
          <p data-refusal={refused.refusal}>{t(`refusal.${refused.refusal}`, { org: poster })}</p>
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
        <SubmitButton variant="primary" busy={busy}>
          {busy ? t("posting") : t("submit")}
        </SubmitButton>
        <Link href={cancelHref} className={cn(standaloneLinkClass, "self-start sm:self-auto")}>
          {t("cancel")}
        </Link>
      </div>
    </Form>
  );
}
