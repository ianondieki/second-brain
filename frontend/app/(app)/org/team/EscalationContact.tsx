"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

import { TeamSelect } from "./fields";
import { teamCalls, type TeamCalls } from "./calls";
import { useTeamWrite } from "./useTeamWrite";

/**
 * The escalation contact (REQ-TEN-02; P28 track B's escalations reach them as well as the admins): one select of the
 * organisation's members, or nobody besides the admins, saved with Save (PUT …/escalation-contact {user_id|null}).
 */
export function EscalationContact({
  orgId,
  members,
  current,
  enrolled,
  calls,
}: {
  orgId: string;
  members: readonly { user_id: string; name: string }[];
  current: string | null;
  enrolled: boolean;
  calls?: TeamCalls;
}) {
  const t = useStrings("teamAdmin");
  const id = useId();
  const api = calls ?? teamCalls(orgId);
  const write = useTeamWrite({ enrolled });
  const [picked, setPicked] = useState(current ?? "");
  const [saved, setSaved] = useState(false);
  const done = useRef<HTMLDivElement>(null);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (write.busy) return;
    setSaved(false);
    void write.run(
      () => api.setEscalationContact(picked || null),
      () => {
        setSaved(true);
        requestAnimationFrame(() => done.current?.focus());
      },
    );
  }

  if (write.stepUp) return <div>{write.stepUp}</div>;

  return (
    <form onSubmit={save} className="flex max-w-xl flex-col gap-5" data-escalation-form="">
      {saved ? (
        <Alert ref={done} tone="ok" className="w-full">
          <p>{t("escalationSaved")}</p>
        </Alert>
      ) : null}
      {write.problem}
      <TeamSelect
        id={`${id}-contact`}
        name="escalation_contact"
        label={t("escalationLabel")}
        value={picked}
        onChange={(event) => {
          setSaved(false);
          write.reset();
          setPicked(event.target.value);
        }}
      >
        <option value="">{t("adminsOnly")}</option>
        {members.map((member) => (
          <option key={member.user_id} value={member.user_id}>
            {member.name}
          </option>
        ))}
      </TeamSelect>
      <div>
        <Button type="submit" variant="secondary" busy={write.busy} data-save-escalation="">
          {write.busy ? t("saving") : t("saveEscalation")}
        </Button>
      </div>
    </form>
  );
}
