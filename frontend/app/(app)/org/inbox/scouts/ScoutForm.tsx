"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { Form, SubmitButton } from "@/components/ui/Form";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { upgradeHref } from "@/lib/billing/upgrade";

import {
  bodyOf,
  checkDraft,
  draftOf,
  FREQUENCIES,
  MATURITIES,
  MAX_KEYWORD_CHARS,
  MAX_KEYWORDS,
  MAX_NICHES,
  type DraftErrors,
  type Preview,
  type Scout,
  type ScoutDraft,
  type ScoutPlan,
  type ScoutRefusal,
} from "../../scout";
import { scoutCalls, type Refused, type ScoutCalls } from "./calls";
import { ChoiceList, CountyChoice, NicheChoice, type NicheOption, type Option } from "./ScoutFields";
import { ScoutPreview } from "./ScoutPreview";

const MATURITY_LABEL = {
  idea: "maturityValue.idea",
  prototype: "maturityValue.prototypeStage",
  mvp: "maturityValue.mvp",
  live: "maturityValue.live",
} as const;

export interface ScoutFormProps {
  orgId: string;
  orgName: string;
  /** The scout being changed; a new one when absent. */
  scout?: Scout;
  plan: ScoutPlan;
  niches: NicheOption[];
  counties: Option[];
  /** Reviewer seats of the organisation (the only possible digest recipients). */
  reviewers: Option[];
  /** Where a saved scout goes: the Inbox's Scout matches. */
  doneHref: string;
  /** This screen, for the checkout's way back after an upgrade. */
  hereHref: string;
  calls?: ScoutCalls;
}

type Busy = null | "save" | "preview" | "pause";

/**
 * Configure the Scout Agent (REQ-SCOUT-01; docs/spec/06 6.8 "form, not prompt-writing"): niches, keywords to look for
 * and to leave out, counties, how far along, the lowest fit, when it looks, the digest's language and its reviewer
 * seats. Preview shows what it would have matched, nothing saved; Save is the one primary action; a saved scout can be
 * paused and resumed. A 402 says the plan does not include it and links to the next plan up's checkout.
 */
export function ScoutForm(props: ScoutFormProps) {
  const t = useStrings("scoutForm");
  const tf = useStrings("ideaFields");
  const router = useRouter();
  const calls = props.calls ?? scoutCalls;
  const [draft, setDraft] = useState<ScoutDraft>(() => draftOf(props.scout, props.plan));
  const [errors, setErrors] = useState<DraftErrors>({});
  const [busy, setBusy] = useState<Busy>(null);
  const [refused, setRefused] = useState<Refused | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const notice = useRef<HTMLDivElement>(null);
  const previewHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (refused) notice.current?.focus();
  }, [refused]);
  useEffect(() => {
    if (preview) previewHeading.current?.focus();
  }, [preview]);

  function change<K extends keyof ScoutDraft>(key: K, value: ScoutDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    if (key in errors) setErrors((current) => ({ ...current, [key]: undefined }));
  }

  /** The draft's problems, shown by their fields; focus goes to the first. False when there are none. */
  function invalid(): boolean {
    const next = checkDraft(draft);
    setErrors(next);
    const first = (["niches", "include", "exclude", "minFit"] as const).find((key) => next[key]);
    if (first) document.getElementById(`scout-${first}`)?.focus();
    return first !== undefined;
  }

  async function run<T>(kind: Exclude<Busy, null>, call: () => Promise<{ ok: true; value: T } | Refused>) {
    if (busy) return null;
    setBusy(kind);
    setRefused(null);
    const outcome = await call();
    setBusy(null);
    if (!outcome.ok) {
      setRefused(outcome);
      return null;
    }
    return outcome.value;
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || invalid()) return;
    const body = bodyOf(draft);
    const saved = await run("save", () =>
      props.scout ? calls.update(props.orgId, props.scout.id, body) : calls.create(props.orgId, body),
    );
    if (saved) {
      setBusy("save"); // stays busy until the matches replace this screen
      router.push(props.doneHref);
    }
  }

  async function showPreview() {
    if (busy || invalid()) return;
    const result = await run("preview", () => calls.preview(props.orgId, bodyOf(draft)));
    if (result) setPreview(result);
  }

  async function togglePause() {
    if (!props.scout) return;
    const paused = !props.scout.paused;
    const result = await run("pause", () => calls.update(props.orgId, props.scout!.id, { paused }));
    if (result) router.refresh();
  }

  const errorText = (key: keyof DraftErrors): string | undefined => {
    const problem = errors[key];
    if (!problem) return undefined;
    const max = problem === "nichesMax" ? MAX_NICHES : problem === "tooLong" ? MAX_KEYWORD_CHARS : MAX_KEYWORDS;
    return t(`error.${problem}`, { max });
  };

  const upgrade = refused?.refusal === "planLimit" && refused.upgradePlan ? refused.upgradePlan : null;
  return (
    <Form onSubmit={save} className="flex flex-col gap-8" aria-busy={busy ? true : undefined} data-scout-form="">
      {props.scout?.paused ? (
        <Alert tone="info" className="w-full">
          {t("pausedNote")}
        </Alert>
      ) : null}

      <NicheChoice
        id="scout-niches"
        niches={props.niches}
        chosen={draft.niches}
        max={MAX_NICHES}
        error={errorText("niches")}
        onChange={(next) => change("niches", next)}
      />

      <div className="flex flex-col gap-5">
        <TextField
          id="scout-include"
          label={t("include")}
          hint={t("includeHint")}
          value={draft.include}
          error={errorText("include")}
          autoComplete="off"
          onChange={(e) => change("include", e.target.value)}
        />
        <TextField
          id="scout-exclude"
          label={t("exclude")}
          hint={t("excludeHint")}
          value={draft.exclude}
          error={errorText("exclude")}
          autoComplete="off"
          onChange={(e) => change("exclude", e.target.value)}
        />
      </div>

      <CountyChoice
        id="scout-counties"
        counties={props.counties}
        chosen={draft.counties}
        onChange={(next) => change("counties", next)}
      />

      <ChoiceList
        id="scout-maturity"
        legend={t("maturity")}
        hint={t("maturityHint")}
        columns
        options={MATURITIES.map((m) => ({ id: m, label: tf(MATURITY_LABEL[m]) }))}
        chosen={draft.maturity}
        onChange={(next) => change("maturity", next as ScoutDraft["maturity"])}
      />

      <TextField
        id="scout-minFit"
        label={t("minFit")}
        hint={t("minFitHint")}
        inputMode="numeric"
        value={draft.minFit}
        error={errorText("minFit")}
        className="max-w-[8rem]"
        onChange={(e) => change("minFit", e.target.value)}
      />

      <RadioGroup
        id="scout-frequency"
        name="frequency"
        legend={t("frequency")}
        value={draft.frequency}
        onChange={(value) => change("frequency", value)}
        options={FREQUENCIES.map((f) => ({
          value: f,
          label: t(`frequencies.${f}`),
          hint: props.plan.frequencies.includes(f) ? undefined : t("notOnPlan"),
        }))}
      />

      <SelectField
        id="scout-language"
        label={t("language")}
        value={draft.language}
        className="max-w-[16rem]"
        onChange={(e) => change("language", e.target.value === "sw" ? "sw" : "en")}
      >
        <option value="en">{t("languages.en")}</option>
        <option value="sw">{t("languages.sw")}</option>
      </SelectField>

      {props.reviewers.length > 0 ? (
        <ChoiceList
          id="scout-recipients"
          legend={t("recipients")}
          hint={t("recipientsHint", { org: props.orgName })}
          options={props.reviewers}
          chosen={draft.recipients}
          onChange={(next) => change("recipients", next)}
        />
      ) : (
        <div className="flex flex-col gap-1">
          <p className="font-medium text-ink">{t("recipients")}</p>
          <p className="text-sm text-ink-soft">{t("noReviewers", { org: props.orgName })}</p>
        </div>
      )}

      {refused ? (
        <Alert ref={notice} className="w-full" tone="error">
          <p data-refusal={refused.refusal}>{refusalText(t, refused.refusal, props.orgName)}</p>
          {upgrade ? (
            <Link
              href={upgradeHref(upgrade, { org: props.orgId, next: props.hereHref })}
              className={standaloneLinkClass}
              data-upgrade=""
            >
              {t("upgrade")}
            </Link>
          ) : null}
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 border-t border-line pt-6 sm:flex-row sm:flex-wrap">
        <SubmitButton variant="primary" busy={busy !== null}>
          {busy === "save" ? t("saving") : t("save")}
        </SubmitButton>
        <Button variant="secondary" busy={busy !== null} onClick={() => void showPreview()} data-preview-button="">
          {busy === "preview" ? t("previewing") : t("preview")}
        </Button>
        {props.scout ? (
          <Button variant="link" busy={busy !== null} onClick={() => void togglePause()} className="sm:ml-auto">
            {props.scout.paused ? t("resume") : t("pause")}
          </Button>
        ) : null}
      </div>

      {preview ? <ScoutPreview preview={preview} headingRef={previewHeading} /> : null}
    </Form>
  );
}

function refusalText(t: ReturnType<typeof useStrings<"scoutForm">>, refusal: ScoutRefusal, org: string): string {
  return t(`refusal.${refusal}`, { org });
}
