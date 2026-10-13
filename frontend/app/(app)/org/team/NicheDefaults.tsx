"use client";

import { useId, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

import { TeamSelect } from "./fields";
import { teamCalls, type TeamCalls } from "./calls";
import { nicheDefaultsBody, type NicheRow } from "./team";
import { useFocusWhen, useTeamWrite } from "./useTeamWrite";

/**
 * The default reviewer per niche (REQ-TEN-02; AT-C-3): one select per niche of the organisation, offering the members
 * who may review (a reviewer, signatory or admin) and "Nobody", saved together with one Save (PUT …/niche-defaults
 * replaces the set). A new engagement in a niche goes to its default unless someone already assigned it.
 */
export function NicheDefaults({
  orgId,
  rows,
  choices,
  enrolled,
  calls,
}: {
  orgId: string;
  rows: readonly NicheRow[];
  /** The members who may be a default reviewer (team.ts reviewerChoices). */
  choices: readonly { user_id: string; name: string }[];
  enrolled: boolean;
  calls?: TeamCalls;
}) {
  const t = useStrings("teamAdmin");
  const id = useId();
  const api = calls ?? teamCalls(orgId);
  const write = useTeamWrite({ enrolled });
  const [picked, setPicked] = useState<Record<string, string>>(() =>
    Object.fromEntries(rows.map((row) => [row.slug, row.userId ?? ""])),
  );
  const [saved, setSaved] = useState(false);
  const done = useFocusWhen(saved);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (write.busy) return;
    setSaved(false);
    const { items } = nicheDefaultsBody(picked);
    void write.run(
      () => api.setNicheDefaults(items),
      () => {
        setSaved(true);
      },
    );
  }

  if (write.stepUp) return <div>{write.stepUp}</div>;

  return (
    <form onSubmit={save} className="flex max-w-xl flex-col gap-5" data-niche-defaults="">
      {saved ? (
        <Alert ref={done} tone="ok" className="w-full">
          <p>{t("defaultsSaved")}</p>
        </Alert>
      ) : null}
      {write.problem}
      {rows.map((row) => {
        const current = picked[row.slug] ?? "";
        return (
          <TeamSelect
            key={row.slug}
            id={`${id}-${row.slug}`}
            name={row.slug}
            label={row.name}
            value={current}
            data-niche={row.slug}
            onChange={(event) => {
              const value = event.target.value;
              setSaved(false);
              write.reset();
              setPicked((all) => ({ ...all, [row.slug]: value }));
            }}
          >
            <option value="">{t("nobody")}</option>
            {choices.map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {member.name}
              </option>
            ))}
          </TeamSelect>
        );
      })}
      <div>
        <Button type="submit" variant="secondary" busy={write.busy} data-save-defaults="">
          {write.busy ? t("saving") : t("saveDefaults")}
        </Button>
      </div>
    </form>
  );
}
