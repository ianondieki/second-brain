"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { FieldError } from "@/components/ui/Field";

import { teamCalls, type TeamCalls } from "./calls";
import { ROLES, sortRoles, type OrgRole } from "./team";
import { useTeamWrite } from "./useTeamWrite";

/**
 * A member's open step (REQ-TEN-02), fetched when "Change roles" or "Remove" is pressed (MemberActions): the six roles
 * with Save (an owner's alone: PUT …/roles, which asks for a fresh second factor), or the in-place question saying what
 * removing does before anything happens (their open assignments are cleared). Its own chunk, so the Team page's first
 * load stays inside the JS budget (docs/spec/07 item 5).
 */
export function MemberEditor({
  mode,
  orgId,
  orgName,
  member,
  enrolled,
  calls,
  onClose,
  onSaved,
}: {
  mode: "roles" | "remove";
  orgId: string;
  orgName: string;
  member: { user_id: string; name: string; roles: readonly OrgRole[] };
  enrolled: boolean;
  calls?: TeamCalls;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useStrings("teamAdmin");
  const id = useId();
  const api = calls ?? teamCalls(orgId);
  const write = useTeamWrite({ enrolled });
  const [chosen, setChosen] = useState<ReadonlySet<OrgRole>>(new Set(member.roles));
  const [rolesError, setRolesError] = useState<string | undefined>();
  const first = useRef<HTMLElement | null>(null);

  // Focus follows the step (WCAG 2.4.3): into what opened.
  useEffect(() => {
    first.current?.focus();
  }, []);

  function saveRoles(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (write.busy) return;
    if (chosen.size === 0) {
      setRolesError(t("rolesRequired"));
      document.getElementById(`${id}-role-${ROLES[0]}`)?.focus();
      return;
    }
    void write.run(() => api.setRoles(member.user_id, sortRoles([...chosen])), onSaved);
  }

  function remove() {
    if (write.busy) return;
    // On success the row leaves the page; the Members heading takes focus.
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
        <fieldset className="flex flex-col" aria-describedby={rolesError ? `${id}-roles-error` : undefined}>
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
              <FieldError id={`${id}-roles-error`}>{rolesError}</FieldError>
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
          <Button variant="link" busy={write.busy} onClick={onClose}>
            {t("cancel")}
          </Button>
        </div>
      </form>
    );
  }

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
          <Button variant="secondary" busy={write.busy} onClick={onClose} data-remove-cancel="">
            {t("cancel")}
          </Button>
          <Button variant="danger" busy={write.busy} onClick={remove} data-remove-confirm="">
            {write.busy ? t("removing") : t("removeYes", { name: member.name })}
          </Button>
        </div>
      </div>
    );
}
