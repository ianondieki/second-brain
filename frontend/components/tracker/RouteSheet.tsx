"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button, buttonClass } from "@/components/ui/Button";
import { SheetHandle, sheetClass } from "@/components/ui/ConfirmDialog";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";

import type { Refusal } from "./calls";
import { nairobiToday } from "./input";
import type { CommandRequest, ProcurementRoute } from "./model";
import { JUSTIFICATION_MAX, JUSTIFICATION_MIN, plainJustification, routeRequest, ROUTES } from "./procurement";

// A public entity's procurement route (stage 3b; REQ-ENG-06, AC-TRACK-5; docs/spec/06 6.9): its owner or admin chooses
// how the organisation will buy, writes the justification direct procurement needs, and names the contact-by date of
// stage 3. A native modal <dialog> drawn as the side states' sheets are (a bottom sheet on phones, D-52), opened
// through their lazy chunk (SideSheet) when "Choose the procurement route" is pressed, so the tracker's first load
// carries none of it. The sheet checks what it can (a route, the justification's length, a date); the API decides the
// rest (the business-day window, contact details in the text) and its refusals are said on the field they concern.

export interface RouteSheetProps {
  engagementId: string;
  /** The engagement's organisation, whose path the route is sent under. */
  orgId?: string;
  lockVersion: number;
  busy: boolean;
  /** The refusal of the last attempt, shown above the buttons unless it belongs to a field. */
  problem?: ReactNode;
  /** The notice of the last attempt (a new object each time), whose refusal a field may carry. */
  notice?: { refusal?: Refusal } | null;
  locale?: string;
  /** Today in Nairobi on the platform's clock (the API's `today`); absent: the browser's day. */
  today?: string | null;
  onSubmit: (request: CommandRequest) => void;
  /** The sheet closed without sending (Cancel or Escape). */
  onClose: () => void;
}

type FieldName = "route" | "justification" | "date";

/**
 * API refusals about what was typed, said on the field. The justification's own codes (justification_required,
 * invalid_justification: the sheet already checks both lengths, so the API's count differs only where it drops
 * characters the field shows) and the schema's refusal of its characters arrive as a plain 422 ("invalid": calls.ts
 * keeps this sheet's codes out of the first load); the route and the date are always well formed here, so a plain
 * 422 is the justification's.
 */
const FIELD_OF: Partial<Record<Refusal, FieldName>> = {
  invalid: "justification",
  containsContact: "justification",
  invalidContactBy: "date",
};

export function RouteSheet(props: RouteSheetProps) {
  const t = useStrings("procurement");
  const ta = useStrings("trackerActions");
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const id = useId();
  const locale = props.locale ?? "en";
  const today = props.today ?? nairobiToday();
  const [route, setRoute] = useState<ProcurementRoute | null>(null);
  const [text, setText] = useState("");
  const [by, setBy] = useState(today);
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({});
  // A refusal about a field is said on it until that field changes, and focus goes back to the field.
  const code = props.notice?.refusal;
  const field = code ? FIELD_OF[code] : undefined;
  const [edited, setEdited] = useState<object | null | undefined>(null);
  const direct = route === "direct";
  const refused =
    field && props.notice && props.notice !== edited
      ? ta(code === "invalid" ? "refusal.invalidJustification" : `refusal.${code!}`)
      : undefined;
  const ids = { route: `${id}-route`, justification: `${id}-justification`, date: `${id}-date` };

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    dialog.querySelector<HTMLElement>("input[type=radio]")?.focus();
  }, []);

  const refusedField = field ? ids[field] : undefined;
  useEffect(() => {
    if (refusedField && props.notice) document.getElementById(refusedField)?.focus();
  }, [props.notice, refusedField]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (props.busy) return;
    const value = plainJustification(text);
    const next: Partial<Record<FieldName, string>> = {
      route: route ? undefined : t("sheet.error.route"),
      justification:
        value.length > JUSTIFICATION_MAX
          ? t("sheet.error.justificationLong")
          : direct && value.length < JUSTIFICATION_MIN
            ? ta("refusal.justificationRequired")
            : undefined,
      date: /^\d{4}-\d{2}-\d{2}$/.test(by) ? undefined : ta("form.date"),
    };
    setErrors(next);
    const first = (["route", "justification", "date"] as const).find((name) => next[name]);
    if (first || !route) {
      // The route's error goes to its first radio; the others to their field.
      const box = document.getElementById(ids[first ?? "route"]);
      (first === "date" || first === "justification" ? box : box?.querySelector<HTMLElement>("input"))?.focus();
      return;
    }
    props.onSubmit(
      routeRequest(props.engagementId, props.orgId ?? "", props.lockVersion, {
        route,
        justification: value || null,
        contact_by: by,
      }),
    );
  }

  function edit(name: FieldName) {
    setEdited(props.notice);
    setErrors((current) => (current[name] ? { ...current, [name]: undefined } : current));
  }

  const count = new Intl.NumberFormat(`${locale}-KE`);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        if (props.busy) event.preventDefault();
      }}
      onClose={props.onClose}
      data-sheet=""
      data-route-sheet=""
      className={sheetClass("lg")}
    >
      <SheetHandle />
      <h2 id={titleId} className="text-lg text-ink">
        {ta("command.choose_route")}
      </h2>
      {/* The page behind a modal sheet is inert: the sheet says "Working…" itself while its step runs. */}
      <span aria-live="polite" data-working="" className="sr-only">
        {props.busy ? ta("busy") : ""}
      </span>
      <form noValidate onSubmit={submit} data-command-form="choose_route" className="mt-3 flex flex-col gap-6">
        <p className="max-w-[60ch] text-ink">{t("sheet.lead")}</p>

        <RadioGroup
          id={ids.route}
          name={`${id}-routes`}
          legend={t("sheet.legend")}
          value={route}
          error={errors.route}
          onChange={(value) => {
            setRoute(value);
            edit("route");
            // A shorter rule may now apply to the text: its error is checked again on Confirm.
            setErrors((current) => (current.justification ? { ...current, justification: undefined } : current));
          }}
          options={ROUTES.map((value) => ({ value, label: t(`route.${value}`), hint: t(`hint.${value}`) }))}
        />

        <TextAreaField
          id={ids.justification}
          label={direct ? t("sheet.justificationRequired") : t("sheet.justificationOptional")}
          hint={direct ? t("sheet.justificationHintDirect") : t("sheet.justificationHint")}
          meter={t("sheet.count", { count: count.format(text.length), max: count.format(JUSTIFICATION_MAX) })}
          maxLength={JUSTIFICATION_MAX}
          rows={4}
          value={text}
          aria-required={direct || undefined}
          error={errors.justification ?? (field === "justification" ? refused : undefined)}
          onChange={(e) => {
            setText(e.target.value);
            edit("justification");
          }}
        />

        <TextField
          id={ids.date}
          type="date"
          label={t("sheet.by")}
          hint={t("sheet.byHint")}
          min={today}
          value={by}
          error={errors.date ?? (field === "date" ? refused : undefined)}
          onChange={(e) => {
            setBy(e.target.value);
            edit("date");
          }}
          className="max-w-[14rem]"
        />

        {field ? null : props.problem}

        {/* Cancel first, on top on phones and on the left from 640 px (the sheets' order); the confirm button is
            styled, not marked, as primary: the screen's data-primary stays on the page's own action. */}
        <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" busy={props.busy} onClick={() => ref.current?.close()} data-dialog-cancel="">
            {ta("cancel")}
          </Button>
          <button type="submit" aria-disabled={props.busy || undefined} data-dialog-confirm="" className={buttonClass("primary")}>
            {props.busy ? ta("busy") : t("sheet.submit")}
          </button>
        </div>
      </form>
    </dialog>
  );
}
