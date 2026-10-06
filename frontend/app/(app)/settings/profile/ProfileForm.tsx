"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Form, SubmitButton } from "@/components/ui/Form";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";

import { HEADLINE_MAX, type Profile } from "@/app/(app)/dev/teams/teams";

import { profileCalls, profileChange, type ProfileCalls } from "./calls";

/**
 * Settings › Profile (REQ-DEV-03; D-58): the headline, the county (the select the Brief form uses) and the "Visible to
 * peers" switch with its one sentence (who sees what, and never organisations). Nothing is kept until "Save", the
 * screen's one primary action; then a status line says it was saved and takes focus. Only what changed is sent (a
 * county change counts toward the API's daily limit).
 */
export function ProfileForm({
  initial,
  counties,
  calls: given,
}: {
  initial: Profile;
  counties: readonly { code: string; name: string }[];
  calls?: Partial<ProfileCalls>;
}) {
  const t = useStrings("profileSettings");
  const [calls] = useState<ProfileCalls>(() => ({ ...profileCalls(), ...given }));
  const [saved, setSaved] = useState(initial);
  const [headline, setHeadline] = useState(initial.headline ?? "");
  const [county, setCounty] = useState(initial.county_code ?? "");
  const [visible, setVisible] = useState(initial.peers_visible);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string; n: number } | null>(null);
  const status = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  function say(ok: boolean, text: string) {
    setSaid((now) => ({ ok, text, n: (now?.n ?? 0) + 1 }));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const change = profileChange(saved, { headline, county, visible });
    if (Object.keys(change).length === 0) {
      say(true, t("saved"));
      return;
    }
    setBusy(true);
    const outcome = await calls.save(change);
    setBusy(false);
    if (!outcome.ok) {
      say(false, t(outcome.refusal));
      return;
    }
    setSaved(outcome.profile);
    say(true, t("saved"));
  }

  return (
    <Form onSubmit={(event) => void save(event)} className="flex flex-col gap-6" data-profile-form="">
      <p className="text-ink">{t("handle", { name: initial.handle })}</p>
      <TextField
        id="profile-headline"
        label={t("headline")}
        hint={t("headlineHint")}
        value={headline}
        maxLength={HEADLINE_MAX}
        onChange={(event) => setHeadline(event.currentTarget.value)}
      />
      <SelectField id="profile-county" label={t("county")} value={county} onChange={(event) => setCounty(event.currentTarget.value)}>
        <option value="">{t("countyNone")}</option>
        {counties.map((item) => (
          <option key={item.code} value={item.code}>
            {item.name}
          </option>
        ))}
      </SelectField>

      <div className="flex flex-col gap-1" data-peers-visible={visible ? "on" : "off"}>
        <span className="inline-flex items-center gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={visible}
            aria-describedby="peers-visible-explain"
            onClick={() => setVisible((now) => !now)}
            className="group inline-flex min-h-11 items-center gap-3 font-semibold text-ink"
          >
            <span
              aria-hidden="true"
              className="relative h-6 w-10 shrink-0 rounded-full border border-ink-soft bg-field transition-colors group-aria-checked:border-accent group-aria-checked:bg-accent motion-reduce:transition-none"
            >
              <span className="absolute top-0.5 left-0.5 size-4 rounded-full bg-ink-soft transition-transform group-aria-checked:translate-x-4 group-aria-checked:bg-on-accent motion-reduce:transition-none" />
            </span>
            {t("visible")}
          </button>
          <span aria-hidden="true" className="text-sm text-ink-soft">
            {visible ? t("on") : t("off")}
          </span>
        </span>
        <p id="peers-visible-explain" className="max-w-[60ch] text-sm text-ink-soft">
          {t("explain")}
        </p>
      </div>

      {said ? (
        <Alert key={said.n} ref={status} tone={said.ok ? "ok" : "error"}>
          {said.text}
        </Alert>
      ) : null}
      <div>
        <SubmitButton variant="primary" busy={busy} data-save-profile="">
          {busy ? t("saving") : t("save")}
        </SubmitButton>
      </div>
    </Form>
  );
}
