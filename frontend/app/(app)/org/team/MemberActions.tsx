"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { FieldError } from "@/components/ui/Field";

import { teamCalls, type TeamCalls } from "./calls";
import { ROLES, sortRoles, type OrgRole } from "./team";

import { useTeamWrite } from "./useTeamWrite";

type Mode = "idle" | "roles" | "remove";

/**
 * A member's actions for an owner or admin (REQ-TEN-02): "Change roles" (an owner's alone: PUT …/roles, which asks for
 * a fresh second factor) opens the six roles in place with Save; "Remove" asks in place, saying what removing does,
 * before anything happens (their open assignments are cleared; a fresh second factor may be asked for first). The
 * last owner and the protected roles are refused by the API and said here in words.
 */
export function MemberActions({
  orgId,
  orgName,
  member,
  canChangeRoles,
  canRemove,
  enrolled,
  calls,
}: {
  orgId: string;
  orgName: string;
  member: { user_id: string; name: string; roles: readonly OrgRole[] };
  canChangeRoles: boolean;
  canRemove: boolean;
  enrolled: boolean;
  calls?: TeamCalls;
}) {
  const t = useStrings("teamAdmin");
  const id = useId();
  const api = calls ?? teamCalls(orgId);
  const write = useTeamWrite({ enrolled });
  const [mode, setMode] = useState<Mode>("idle");
  const [chosen, setChosen] = useState<ReadonlySet<OrgRole>>(new Set(member.roles));
  const [rolesError, setRolesError] = useState<string | undefined>();
  const [saved, setSaved] = useState(false);
  // The button that opened the step, to give focus back to when it closes (the idle buttons are drawn anew).
  const returnTo = useRef<Mode>("idle");
  const actions = useRef<HTMLDivElement>(null);
  const first = useRef<HTMLElement | null>(null);
  const done = useRef<HTMLDivElement>(null);

  // Focus follows the step (WCAG 2.4.3): into what opened, back to its button when it closes.
  useEffect(() => {
    if (mode !== "idle") {
      first.current?.focus();
      return;
    }
    const back = returnTo.current;
    returnTo.current = "idle";
    if (back === "idle") return;
    const selector = back === "roles" ? "[data-change-roles]" : "[data-remove]";
    actions.current?.querySelector<HTMLElement>(selector)?.focus();
  }, [mode]);

  function close() {
    returnTo.current = mode;
    setMode("idle");
    write.reset();
    setRolesError(undefined);
  }

  function open(next: Mode) {
    setSaved(false);
    write.reset();
    if (next === "roles") setChosen(new Set(member.roles));
    setMode(next);
  }

  function saveRoles(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (write.busy) return;
    if (chosen.size === 0) {
      setRolesError(t("rolesRequired"));
      document.getElementById(`${id}-role-${ROLES[0]}`)?.focus();
      return;
    }
    void write.run(
      () => api.setRoles(member.user_id, sortRoles([...chosen])),
      () => {
        setMode("idle");
        setSaved(true);
        requestAnimationFrame(() => done.current?.focus());
      },
    );
  }

  function remove() {
    if (write.busy) return;
    // On success the row leaves the page; the Members heading takes focus (the page's own handler, team-focus).
    void write.run(
      () => api.remove(member.user_id),
      () => document.getElementById("team-members")?.focus(),
    );
  }

  if (write.stepUp) return <div className="mt-1 w-full sm:col-span-2">{write.stepUp}</div>;

  if (mode === "roles") {
    return (
      <form
        onSubmit={saveRoles}
        className="mt-1 flex w-full flex-col gap-4 sm:col-span-2"
        data-member-roles={member.user_id}
      >
        {write.problem}
        <fieldset className="flex flex-col">
          <legend
            ref={(node) => {
              first.current = node;
            }}
            tabIndex={-1}
            className="font-medium text-ink focus:outline-none"
          >
            {t("rolesFor", { name: member.name })}
          </legend>
          {rolesError ? (
            <div className="mt-1.5">
              <FieldError>{rolesError}</FieldError>
            </div>
          ) : null}
          <div className="mt-1 grid gap-x-6 sm:grid-cols-2">
            {ROLES.map((role) => (
              <Checkbox
                key={role}
                id={`${id}-role-${role}`}
                checked={chosen.has(role)}
                onChange={(event) => {
                  const on = event.target.checked;
                  setRolesError(undefined);
                  setChosen((current) => {
                    const next = new Set(current);
                    if (on) next.add(role);
                    else next.delete(role);
                    return next;
                  });
                }}
                label={t(`role.${role}`)}
              />
            ))}
          </div>
        </fieldset>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button type="submit" variant="secondary" busy={write.busy}>
            {write.busy ? t("saving") : t("saveRoles")}
          </Button>
          <Button variant="link" busy={write.busy} onClick={close}>
            {t("cancel")}
          </Button>
        </div>
      </form>
    );
  }

  if (mode === "remove") {
    return (
      <div className="mt-1 flex w-full flex-col gap-4 sm:col-span-2" data-member-remove={member.user_id}>
        <p
          ref={(node) => {
            first.current = node;
          }}
          tabIndex={-1}
          className="max-w-[60ch] text-ink focus:outline-none"
        >
          {t("removeConfirm", { name: member.name, org: orgName })}
        </p>
        {write.problem}
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button variant="secondary" busy={write.busy} onClick={close} data-remove-cancel="">
            {t("cancel")}
          </Button>
          <Button variant="danger" busy={write.busy} onClick={remove} data-remove-confirm="">
            {write.busy ? t("removing") : t("removeYes", { name: member.name })}
          </Button>
        </div>
      </div>
    );
  }

  if (!canChangeRoles && !canRemove) return null;
  return (
    <div
      ref={actions}
      // Under 640 px the actions sit under the person's words, past the initials (36 px + 14 px gap).
      className="flex flex-col gap-2 pl-[3.125rem] sm:col-start-2 sm:row-start-1 sm:items-end sm:pl-0"
      data-member-actions={member.user_id}
    >
      <div className="flex gap-2">
        {canChangeRoles ? (
          <Button
            variant="link"
            onClick={() => open("roles")}
            aria-label={t("changeRolesLabel", { name: member.name })}
            data-change-roles=""
          >
            {t("changeRoles")}
          </Button>
        ) : null}
        {canRemove ? (
          <Button
            variant="link"
            onClick={() => open("remove")}
            aria-label={t("removeLabel", { name: member.name })}
            data-remove=""
          >
            {t("remove")}
          </Button>
        ) : null}
      </div>
      {saved ? (
        <Alert ref={done} tone="ok" className="w-full">
          <p>{t("rolesSaved")}</p>
        </Alert>
      ) : null}
    </div>
  );
}
