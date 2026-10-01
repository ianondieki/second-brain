"use client";

import { haptic } from "@/lib/haptics";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import type { confirmStepUp } from "@/components/tracker/calls";
import { nairobiToday } from "@/components/tracker/model";
import { StepUp } from "@/components/tracker/StepUp";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Form, SubmitButton } from "@/components/ui/Form";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import { interestRefusalOf, type InterestRefusal } from "../../../scout";

type Channel = components["schemas"]["ContactChannel"];
type Body = components["schemas"]["InterestBody"];
const CHANNELS = ["email", "phone", "whatsapp", "video_call", "in_person"] as const satisfies readonly Channel[];

export interface Member {
  user_id: string;
  display_name: string;
}

export interface ExpressInterestProps {
  orgId: string;
  orgName: string;
  matchId: string;
  proposalId: string;
  /** The organisation's active members (the contact person); null when they could not be read. */
  members: Member[] | null;
  myUserId: string;
  /** Two-step sign-in is on (the step-up needs a code). */
  enrolled: boolean;
  /** "?org=<id>" kept on the tracker link for members of several organisations. */
  query: string;
  post?: (body: Body) => Promise<{ ok: true; engagementId: string } | { ok: false; refusal: InterestRefusal }>;
  confirmImpl?: typeof confirmStepUp;
}

/** POST /api/orgs/{org_id}/interest from a scout match (origin org_agent_match): the engagement's id, or a refusal. */
async function postInterest(orgId: string, body: Body) {
  try {
    const { data, error, response } = await api.POST("/api/orgs/{org_id}/interest", {
      params: { path: { org_id: orgId } },
      body,
    });
    if (data) return { ok: true as const, engagementId: data.id };
    return { ok: false as const, refusal: interestRefusalOf(response.status, error) };
  } catch {
    return { ok: false as const, refusal: "network" as const };
  }
}

type Mode = "idle" | "form" | "stepUp" | "sent";

/**
 * Express interest (docs/spec/06 6.9 stage 0; REQ-ENG-04): the signatory names who will contact the developer, how
 * and by when; the API opens an ORG_INTEREST engagement and tells the developer (N17). A second factor older than 12
 * hours asks for a fresh code inline (the tracker's step-up), then the request runs once more. On success the
 * tracker opens. Refusals are fixed sentences, never the server's text.
 */
export function ExpressInterest(props: ExpressInterestProps) {
  const t = useStrings("expressInterest");
  const router = useRouter();
  const id = useId();
  const [mode, setMode] = useState<Mode>("idle");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Exclude<InterestRefusal, "stepUp"> | null>(null);
  const members = props.members ?? [];
  const [person, setPerson] = useState(
    members.find((m) => m.user_id === props.myUserId)?.user_id ?? members[0]?.user_id ?? "",
  );
  const [channel, setChannel] = useState<Channel>("email");
  const today = nairobiToday();
  const [by, setBy] = useState(today);
  const [errors, setErrors] = useState<{ person?: string; by?: string }>({});
  const notice = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLParagraphElement>(null);
  const post = props.post ?? ((body: Body) => postInterest(props.orgId, body));

  useEffect(() => {
    if (refusal) notice.current?.focus();
  }, [refusal]);
  // Focus follows what changed (WCAG 2.4.3): a refusal takes it (also after a step-up), else the opened form's lead;
  // Cancel gives it back to Express interest.
  const returnFocus = useRef(false);
  const shown = useRef<Mode>(mode);
  useEffect(() => {
    const opened = mode !== shown.current;
    shown.current = mode;
    if (mode === "form" && opened && !refusal) heading.current?.focus();
    if (mode === "idle" && returnFocus.current) {
      returnFocus.current = false;
      document.querySelector<HTMLElement>("[data-express-interest]")?.focus();
    }
  }, [mode, refusal]);

  function body(): Body {
    return {
      proposal_id: props.proposalId,
      origin: "org_agent_match",
      match_id: props.matchId,
      contact_user_id: person,
      channel,
      contact_by: by,
    };
  }

  async function send(retried = false) {
    if (busy && !retried) return;
    setBusy(true);
    setRefusal(null);
    const outcome = await post(body());
    if (outcome.ok) {
      setMode("sent");
      haptic("success");
      router.push(`/org/engagements/${encodeURIComponent(outcome.engagementId)}${props.query}`);
      return;
    }
    setBusy(false);
    if (outcome.refusal === "stepUp" && !retried) {
      setMode("stepUp");
      return;
    }
    setMode("form");
    setRefusal(outcome.refusal === "stepUp" ? "generic" : outcome.refusal);
    // The organisation now has an engagement (or the match is gone): the page shows where things stand.
    if (outcome.refusal === "engagement_exists" || outcome.refusal === "proposal_unavailable") router.refresh();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const next = { person: person ? undefined : t("required"), by: by ? undefined : t("date") };
    setErrors(next);
    if (next.person) return document.getElementById(`${id}-person`)?.focus();
    if (next.by) return document.getElementById(`${id}-by`)?.focus();
    void send();
  }

  const alert = refusal ? (
    <Alert ref={notice} className="w-full" tone="error">
      <p data-refusal={refusal}>{t(`refusal.${refusal}`, { org: props.orgName })}</p>
    </Alert>
  ) : null;

  if (mode === "sent") {
    return (
      <Alert tone="ok" className="w-full">
        {t("sent")}
      </Alert>
    );
  }

  if (mode === "stepUp") {
    return (
      <StepUp
        enrolled={props.enrolled}
        onCancel={() => {
          setMode("form");
          setBusy(false);
        }}
        onConfirmed={() => send(true)}
        confirmImpl={props.confirmImpl}
      />
    );
  }

  if (mode === "idle") {
    return (
      <Button variant="primary" onClick={() => setMode("form")} data-express-interest="">
        {t("button")}
      </Button>
    );
  }

  if (props.members === null) {
    return (
      <div className="flex flex-col items-start gap-4">
        <Alert className="w-full">{t("membersFailed", { org: props.orgName })}</Alert>
        <Button
          variant="secondary"
          onClick={() => {
            returnFocus.current = true;
            setMode("idle");
          }}
        >
          {t("cancel")}
        </Button>
      </div>
    );
  }

  return (
    <Form onSubmit={submit} data-interest-form="" className="flex flex-col gap-5" aria-busy={busy || undefined}>
      <p ref={heading} tabIndex={-1} className="max-w-[60ch] text-ink focus:outline-none">
        {t("formLead", { org: props.orgName })}
      </p>
      <SelectField
        id={`${id}-person`}
        label={t("person")}
        value={person}
        error={errors.person}
        onChange={(e) => {
          setPerson(e.target.value);
          setErrors((current) => ({ ...current, person: undefined }));
        }}
      >
        {members.map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.display_name}
          </option>
        ))}
      </SelectField>
      <SelectField
        id={`${id}-channel`}
        label={t("channel")}
        value={channel}
        onChange={(e) => setChannel(e.target.value as Channel)}
      >
        {CHANNELS.map((c) => (
          <option key={c} value={c}>
            {t(`channels.${c}`)}
          </option>
        ))}
      </SelectField>
      <TextField
        id={`${id}-by`}
        type="date"
        label={t("by")}
        hint={t("byHint")}
        min={today}
        value={by}
        error={errors.by}
        onChange={(e) => {
          setBy(e.target.value);
          setErrors((current) => ({ ...current, by: undefined }));
        }}
        className="max-w-[14rem]"
      />
      {alert}
      <div className="flex flex-col gap-3 sm:flex-row">
        <SubmitButton variant="primary" busy={busy}>
          {busy ? t("sending") : t("submit")}
        </SubmitButton>
        <Button
          variant="secondary"
          onClick={() => {
            setRefusal(null);
            returnFocus.current = true;
            setMode("idle");
          }}
        >
          {t("cancel")}
        </Button>
      </div>
    </Form>
  );
}
