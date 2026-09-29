"use client";

import { useId, useState, type FormEvent, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Form, SubmitButton } from "@/components/ui/Form";
import { SelectField } from "@/components/ui/SelectField";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";

import {
  nairobiToday,
  toMinor,
  type ApproveInput,
  type ConfirmPaymentInput,
  type DeclineInput,
  type FormCommand,
  type FormInput,
  type PaymentInput,
  type TermsInput,
} from "./model";

// The small forms of the commands whose request carries more than lock_version (backend openapi.json: ApproveBody,
// DeclineBody, TermsBody, PaymentBody, ConfirmPaymentBody). They check only what is needed to send; the API decides
// the rest (a 422 comes back as a refusal next to the form). Loaded when a form opens (Actions.tsx).

export interface Member {
  user_id: string;
  display_name: string;
}

export interface CommandFormProps {
  command: FormCommand;
  busy: boolean;
  /** Where the refusal of the last attempt shows (inside the form, above its buttons). */
  notice?: ReactNode;
  onSubmit: (input: FormInput) => void;
  onCancel: () => void;
  /** approve: the organisation's active members, and who is signed in (the default contact person). */
  members?: Member[];
  myUserId?: string;
  /** confirm_payment: the organisation's recorded amount, shown as a hint (never filled in for the developer). */
  recorded?: string | null;
  today?: string;
}

type Errors = Record<string, string | undefined>;

const IP_TERMS = [
  "non_exclusive_licence",
  "development_contract",
  "revenue_share",
  "exclusive_licence",
  "assignment",
] as const satisfies ReadonlyArray<TermsInput["ip_terms"]>;
const CHANNELS = ["email", "phone", "whatsapp", "video_call", "in_person"] as const satisfies ReadonlyArray<
  ApproveInput["contact_channel"]
>;
const DECLINE_REASONS = [
  "NOT_PRIORITY",
  "ALREADY_IN_PROGRESS_INTERNALLY",
  "BUDGET",
  "NOT_RELEVANT",
  "NEEDS_MATURITY",
  "OTHER",
] as const satisfies ReadonlyArray<DeclineInput["reason"]>;
const METHODS = ["mpesa", "bank", "other"] as const satisfies ReadonlyArray<PaymentInput["method"]>;

export function CommandForm(props: CommandFormProps) {
  const today = props.today ?? nairobiToday();
  switch (props.command) {
    case "approve":
      return <ApproveForm {...props} today={today} />;
    case "decline":
      return <DeclineForm {...props} today={today} />;
    case "propose_terms":
      return <TermsForm {...props} today={today} />;
    case "record_payment":
      return <PaymentForm {...props} today={today} />;
    case "confirm_payment":
      return <ConfirmPaymentForm {...props} />;
  }
}

function Shell({
  props,
  onSubmit,
  children,
}: {
  props: CommandFormProps;
  onSubmit: () => void;
  children: ReactNode;
}) {
  const t = useStrings("trackerActions");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!props.busy) onSubmit();
  }
  return (
    <Form onSubmit={submit} data-command-form={props.command} className="flex flex-col gap-5">
      {children}
      {props.notice}
      <div className="flex flex-col gap-3 sm:flex-row">
        <SubmitButton variant="primary" busy={props.busy}>
          {props.busy ? t("busy") : t(`command.${props.command}`)}
        </SubmitButton>
        <Button variant="secondary" onClick={props.onCancel}>
          {t("cancel")}
        </Button>
      </div>
    </Form>
  );
}

/** Focuses the first field with an error after a refused submit. */
function focusFirst(errors: Errors, ids: Record<string, string>) {
  const first = Object.keys(errors).find((key) => errors[key]);
  if (first && ids[first]) document.getElementById(ids[first])?.focus();
}

function ApproveForm(props: CommandFormProps & { today: string }) {
  const t = useStrings("trackerActions");
  const id = useId();
  const members = props.members ?? [];
  const [person, setPerson] = useState(
    members.find((m) => m.user_id === props.myUserId)?.user_id ?? members[0]?.user_id ?? "",
  );
  const [channel, setChannel] = useState<ApproveInput["contact_channel"]>("email");
  const [by, setBy] = useState(props.today);
  const [errors, setErrors] = useState<Errors>({});
  const ids = { person: `${id}-person`, by: `${id}-by` };

  function submit() {
    const next: Errors = { person: person ? undefined : t("form.required"), by: by ? undefined : t("form.date") };
    setErrors(next);
    if (next.person || next.by) return focusFirst(next, ids);
    props.onSubmit({ contact_user_id: person, contact_channel: channel, contact_by: by } satisfies ApproveInput);
  }

  return (
    <Shell props={props} onSubmit={submit}>
      <p className="max-w-[60ch] text-ink">{t("approve.lead")}</p>
      <SelectField id={ids.person} label={t("approve.person")} value={person} error={errors.person} onChange={(e) => setPerson(e.target.value)}>
        {members.map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.display_name}
          </option>
        ))}
      </SelectField>
      <SelectField
        id={`${id}-channel`}
        label={t("approve.channel")}
        value={channel}
        onChange={(e) => setChannel(e.target.value as ApproveInput["contact_channel"])}
      >
        {CHANNELS.map((c) => (
          <option key={c} value={c}>
            {t(`channel.${c}`)}
          </option>
        ))}
      </SelectField>
      <TextField
        id={ids.by}
        type="date"
        label={t("approve.by")}
        hint={t("approve.byHint")}
        min={props.today}
        value={by}
        error={errors.by}
        onChange={(e) => setBy(e.target.value)}
        className="max-w-[14rem]"
      />
    </Shell>
  );
}

function DeclineForm(props: CommandFormProps & { today: string }) {
  const t = useStrings("trackerActions");
  const id = useId();
  const [reason, setReason] = useState<DeclineInput["reason"] | "">("");
  const [other, setOther] = useState("");
  const [started, setStarted] = useState("");
  const [attested, setAttested] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const ids = { reason: `${id}-reason`, other: `${id}-other`, started: `${id}-started`, attested: `${id}-attested` };

  function submit() {
    const internal = reason === "ALREADY_IN_PROGRESS_INTERNALLY";
    const next: Errors = {
      reason: reason ? undefined : t("form.required"),
      other: reason === "OTHER" && !other.trim() ? t("form.required") : undefined,
      started: internal && !started ? t("form.date") : undefined,
      attested: internal && !attested ? t("decline.attestRequired") : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean) || !reason) return focusFirst(next, ids);
    props.onSubmit({
      reason,
      other_text: reason === "OTHER" ? other.trim() : null,
      internal_start_date: internal ? started : null,
      attested: internal && attested,
    } satisfies DeclineInput);
  }

  return (
    <Shell props={props} onSubmit={submit}>
      <p className="max-w-[60ch] text-ink">{t("decline.lead")}</p>
      <SelectField
        id={ids.reason}
        label={t("decline.reason")}
        value={reason}
        error={errors.reason}
        onChange={(e) => setReason(e.target.value as DeclineInput["reason"])}
      >
        <option value="" disabled>
          {t("form.choose")}
        </option>
        {DECLINE_REASONS.map((r) => (
          <option key={r} value={r}>
            {t(`reason.${r}`)}
          </option>
        ))}
      </SelectField>
      {reason === "OTHER" ? (
        <TextAreaField
          id={ids.other}
          label={t("decline.other")}
          hint={t("decline.otherHint")}
          value={other}
          maxLength={1000}
          error={errors.other}
          onChange={(e) => setOther(e.target.value)}
        />
      ) : null}
      {reason === "ALREADY_IN_PROGRESS_INTERNALLY" ? (
        <>
          <TextField
            id={ids.started}
            type="date"
            label={t("decline.started")}
            max={props.today}
            value={started}
            error={errors.started}
            onChange={(e) => setStarted(e.target.value)}
            className="max-w-[14rem]"
          />
          <Checkbox
            id={ids.attested}
            label={t("decline.attest")}
            checked={attested}
            error={errors.attested}
            onChange={(e) => setAttested(e.target.checked)}
          />
        </>
      ) : null}
    </Shell>
  );
}

interface MilestoneDraft {
  key: number;
  deliverable: string;
  amount: string;
  due: string;
  window: string;
}

function TermsForm(props: CommandFormProps & { today: string }) {
  const t = useStrings("trackerActions");
  const id = useId();
  const [ip, setIp] = useState<TermsInput["ip_terms"] | "">("");
  const [deemed, setDeemed] = useState("0");
  const [exclusivity, setExclusivity] = useState("");
  const [rows, setRows] = useState<MilestoneDraft[]>([{ key: 1, deliverable: "", amount: "", due: "", window: "" }]);
  const [errors, setErrors] = useState<Errors>({});

  const rowId = (key: number, field: string) => `${id}-m${key}-${field}`;
  const update = (key: number, patch: Partial<MilestoneDraft>) =>
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  function submit() {
    const next: Errors = {
      ip: ip ? undefined : t("form.required"),
      deemed: /^\d{1,2}$/.test(deemed.trim()) ? undefined : t("form.days"),
    };
    const ids: Record<string, string> = { ip: `${id}-ip`, deemed: `${id}-deemed` };
    for (const row of rows) {
      const key = `m${row.key}`;
      next[`${key}-deliverable`] = row.deliverable.trim() ? undefined : t("form.required");
      next[`${key}-amount`] = toMinor(row.amount) ? undefined : t("form.amount");
      next[`${key}-due`] = row.due ? undefined : t("form.date");
      next[`${key}-window`] = !row.window.trim() || /^\d{1,2}$/.test(row.window.trim()) ? undefined : t("form.days");
      for (const field of ["deliverable", "amount", "due", "window"]) ids[`${key}-${field}`] = rowId(row.key, field);
    }
    setErrors(next);
    if (Object.values(next).some(Boolean) || !ip) return focusFirst(next, ids);
    props.onSubmit({
      ip_terms: ip,
      deemed_acceptance_days: Number(deemed.trim()),
      exclusivity: exclusivity.trim() || null,
      milestones: rows.map((row) => ({
        deliverable: row.deliverable.trim(),
        amount_kes_minor: toMinor(row.amount)!,
        due_date: row.due,
        review_window_bd: row.window.trim() ? Number(row.window.trim()) : null,
      })),
    } satisfies TermsInput);
  }

  return (
    <Shell props={props} onSubmit={submit}>
      <p className="max-w-[60ch] text-ink">{t("terms.lead")}</p>
      <SelectField
        id={`${id}-ip`}
        label={t("terms.ip")}
        hint={t("terms.ipHint")}
        value={ip}
        error={errors.ip}
        onChange={(e) => setIp(e.target.value as TermsInput["ip_terms"])}
      >
        <option value="" disabled>
          {t("form.choose")}
        </option>
        {IP_TERMS.map((term) => (
          <option key={term} value={term}>
            {t(`ipTerms.${term}`)}
          </option>
        ))}
      </SelectField>
      <TextField
        id={`${id}-deemed`}
        inputMode="numeric"
        label={t("terms.deemed")}
        hint={t("terms.deemedHint")}
        value={deemed}
        error={errors.deemed}
        onChange={(e) => setDeemed(e.target.value)}
        className="max-w-[8rem]"
      />
      <TextField
        id={`${id}-exclusivity`}
        label={t("terms.exclusivity")}
        hint={t("terms.exclusivityHint")}
        value={exclusivity}
        maxLength={500}
        onChange={(e) => setExclusivity(e.target.value)}
      />
      {rows.map((row, index) => {
        const key = `m${row.key}`;
        return (
          <fieldset key={row.key} className="flex flex-col gap-4 border-t border-line pt-4">
            <legend className="float-left mb-1 w-full pt-4 font-semibold text-ink">
              {t("terms.milestone", { number: index + 1 })}
            </legend>
            <TextField
              id={rowId(row.key, "deliverable")}
              label={t("terms.deliverable")}
              value={row.deliverable}
              maxLength={500}
              error={errors[`${key}-deliverable`]}
              onChange={(e) => update(row.key, { deliverable: e.target.value })}
            />
            <TextField
              id={rowId(row.key, "amount")}
              inputMode="decimal"
              label={t("terms.amount")}
              value={row.amount}
              error={errors[`${key}-amount`]}
              onChange={(e) => update(row.key, { amount: e.target.value })}
              className="max-w-[14rem]"
            />
            <TextField
              id={rowId(row.key, "due")}
              type="date"
              label={t("terms.due")}
              min={props.today}
              value={row.due}
              error={errors[`${key}-due`]}
              onChange={(e) => update(row.key, { due: e.target.value })}
              className="max-w-[14rem]"
            />
            <TextField
              id={rowId(row.key, "window")}
              inputMode="numeric"
              label={t("terms.window")}
              hint={t("terms.windowHint")}
              value={row.window}
              error={errors[`${key}-window`]}
              onChange={(e) => update(row.key, { window: e.target.value })}
              className="max-w-[8rem]"
            />
            {rows.length > 1 ? (
              <Button
                variant="link"
                className="self-start"
                onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}
              >
                {t("terms.remove", { number: index + 1 })}
              </Button>
            ) : null}
          </fieldset>
        );
      })}
      {rows.length < 20 ? (
        <Button
          variant="secondary"
          className="self-start"
          onClick={() =>
            setRows((current) => [
              ...current,
              { key: Math.max(...current.map((r) => r.key)) + 1, deliverable: "", amount: "", due: "", window: "" },
            ])
          }
        >
          {t("terms.add")}
        </Button>
      ) : null}
    </Shell>
  );
}

function PaymentForm(props: CommandFormProps & { today: string }) {
  const t = useStrings("trackerActions");
  const id = useId();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentInput["method"]>("mpesa");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(props.today);
  const [errors, setErrors] = useState<Errors>({});
  const ids = { amount: `${id}-amount`, paidOn: `${id}-paid` };

  function submit() {
    const minor = toMinor(amount);
    const next: Errors = { amount: minor ? undefined : t("form.amount"), paidOn: paidOn ? undefined : t("form.date") };
    setErrors(next);
    if (!minor || next.paidOn) return focusFirst(next, ids);
    props.onSubmit({
      amount_kes_minor: minor,
      method,
      reference: reference.trim() || null,
      paid_on: paidOn,
    } satisfies PaymentInput);
  }

  return (
    <Shell props={props} onSubmit={submit}>
      <p className="max-w-[60ch] text-ink">{t("payment.lead")}</p>
      <TextField
        id={ids.amount}
        inputMode="decimal"
        label={t("payment.amount")}
        value={amount}
        error={errors.amount}
        onChange={(e) => setAmount(e.target.value)}
        className="max-w-[14rem]"
      />
      <SelectField id={`${id}-method`} label={t("payment.method")} value={method} onChange={(e) => setMethod(e.target.value as PaymentInput["method"])}>
        {METHODS.map((m) => (
          <option key={m} value={m}>
            {t(`paymentMethod.${m}`)}
          </option>
        ))}
      </SelectField>
      <TextField
        id={`${id}-reference`}
        label={t("payment.reference")}
        hint={t("payment.referenceHint")}
        value={reference}
        maxLength={64}
        onChange={(e) => setReference(e.target.value)}
      />
      <TextField
        id={ids.paidOn}
        type="date"
        label={t("payment.paidOn")}
        max={props.today}
        value={paidOn}
        error={errors.paidOn}
        onChange={(e) => setPaidOn(e.target.value)}
        className="max-w-[14rem]"
      />
    </Shell>
  );
}

function ConfirmPaymentForm(props: CommandFormProps) {
  const t = useStrings("trackerActions");
  const id = useId();
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | undefined>();

  function submit() {
    const minor = toMinor(amount);
    if (!minor) {
      setError(t("form.amount"));
      document.getElementById(`${id}-received`)?.focus();
      return;
    }
    setError(undefined);
    props.onSubmit({ amount_received_kes_minor: minor } satisfies ConfirmPaymentInput);
  }

  return (
    <Shell props={props} onSubmit={submit}>
      <p className="max-w-[60ch] text-ink">{t("confirmPayment.lead")}</p>
      <TextField
        id={`${id}-received`}
        inputMode="decimal"
        label={t("confirmPayment.amount")}
        hint={props.recorded ? t("confirmPayment.hint", { value: props.recorded }) : undefined}
        value={amount}
        error={error}
        onChange={(e) => setAmount(e.target.value)}
        className="max-w-[14rem]"
      />
    </Shell>
  );
}
