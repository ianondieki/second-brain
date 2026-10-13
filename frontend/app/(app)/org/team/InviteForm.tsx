"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Checkbox } from "@/components/ui/Checkbox";
import { FieldError } from "@/components/ui/Field";
import { Form, SubmitButton } from "@/components/ui/Form";
import { TextField } from "@/components/ui/TextField";

import { teamCalls, type TeamCalls } from "./calls";
import type { OrgRole } from "./team";
import { useTeamWrite } from "./useTeamWrite";

/** Light checks only (the API is the judge): something before and after one "@", no spaces. */
const LOOKS_LIKE_EMAIL = /^[^\s@]+@[^\s@]+$/;

/**
 * "Invite someone" (REQ-TEN-02): a work email and the roles to give, then Send (the page's one primary action). The
 * API emails a link valid for 7 days; the open invitations below are read again. An admin who is not an owner is
 * offered the roles they may give only (owner and signatory are an owner's to give). A fresh second factor asked for
 * first takes the form's place, then the invitation is sent.
 */
export function InviteForm({
  orgId,
  roles,
  enrolled,
  calls,
}: {
  orgId: string;
  /** The roles this person may give, most powerful first (team.ts grantableRoles). */
  roles: readonly OrgRole[];
  enrolled: boolean;
  calls?: TeamCalls;
}) {
  const t = useStrings("teamAdmin");
  const id = useId();
  const api = calls ?? teamCalls(orgId);
  const write = useTeamWrite({ enrolled, primary: true });
  const [email, setEmail] = useState("");
  const [chosen, setChosen] = useState<ReadonlySet<OrgRole>>(new Set());
  const [errors, setErrors] = useState<{ email?: string; roles?: string }>({});
  const [invited, setInvited] = useState<string | null>(null);
  const done = useRef<HTMLDivElement>(null);

  function toggle(role: OrgRole, on: boolean) {
    setChosen((current) => {
      const next = new Set(current);
      if (on) next.add(role);
      else next.delete(role);
      return next;
    });
    setErrors((current) => ({ ...current, roles: undefined }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (write.busy) return;
    const address = email.trim();
    const next = {
      email: !address ? t("emailRequired") : LOOKS_LIKE_EMAIL.test(address) ? undefined : t("refusal.invalid_email"),
      roles: chosen.size === 0 ? t("rolesRequired") : undefined,
    };
    setErrors(next);
    setInvited(null);
    if (next.email) return document.getElementById(`${id}-email`)?.focus();
    if (next.roles) return document.getElementById(`${id}-role-${roles[0]}`)?.focus();
    const picked = roles.filter((role) => chosen.has(role));
    void write.run(
      () => api.invite(address, picked),
      () => {
        setEmail("");
        setChosen(new Set());
        setInvited(address);
        requestAnimationFrame(() => done.current?.focus());
      },
    );
  }

  if (write.stepUp) return <div data-invite-step-up="">{write.stepUp}</div>;

  return (
    <Form onSubmit={submit} className="flex max-w-xl flex-col gap-5" data-invite-form="">
      {invited ? (
        <Alert ref={done} tone="ok" className="w-full">
          <p data-invited="">{t("invited", { email: invited })}</p>
        </Alert>
      ) : null}
      {write.problem}
      <TextField
        id={`${id}-email`}
        type="email"
        name="email"
        autoComplete="off"
        inputMode="email"
        spellCheck={false}
        maxLength={254}
        label={t("email")}
        hint={t("emailHint")}
        value={email}
        error={errors.email}
        onChange={(event) => {
          setEmail(event.target.value);
          setErrors((current) => ({ ...current, email: undefined }));
          write.reset();
        }}
      />
      <fieldset className="flex flex-col" aria-describedby={errors.roles ? `${id}-roles-error` : undefined}>
        <legend className="font-medium text-ink">{t("rolesLegend")}</legend>
        {roles.length < 6 ? <p className="mt-1.5 text-sm text-ink-soft">{t("rolesOwnerOnly")}</p> : null}
        {errors.roles ? (
          <div className="mt-1.5">
            <FieldError id={`${id}-roles-error`}>{errors.roles}</FieldError>
          </div>
        ) : null}
        <div className="mt-1 grid gap-x-6 sm:grid-cols-2">
          {roles.map((role) => (
            <Checkbox
              key={role}
              id={`${id}-role-${role}`}
              name="roles"
              value={role}
              checked={chosen.has(role)}
              onChange={(event) => toggle(role, event.target.checked)}
              label={
                <span className="flex flex-col">
                  <span className="font-medium">{t(`role.${role}`)}</span>
                  <span className="text-sm text-ink-soft">{t(`roleHint.${role}`)}</span>
                </span>
              }
            />
          ))}
        </div>
      </fieldset>
      <div>
        <SubmitButton variant="primary" busy={write.busy}>
          {write.busy ? t("sending") : t("send")}
        </SubmitButton>
      </div>
    </Form>
  );
}
