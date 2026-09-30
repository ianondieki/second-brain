"use client";

import { useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { FieldError } from "@/components/ui/Field";

import { saveNiches } from "./calls";
import { countIssue, sameIds, toggle, type CountIssue, type NichesProblem } from "./picker";

/** A niche as the picker lists it: a parent with its children (names in the reader's language, from the server). */
export interface PickerNiche {
  id: string;
  name: string;
  children: { id: string; name: string }[];
}

export interface NichePickerProps {
  niches: PickerNiche[];
  /** The ids liked now (empty for a developer who has not chosen yet). */
  initial: string[];
  min: number;
  max: number;
  saveImpl?: typeof saveNiches;
}

type Status = { kind: "idle" } | { kind: "saving" } | { kind: "saved" } | { kind: "refused"; problem: NichesProblem };

/**
 * The liked-niches picker (REQ-PERS-03; docs/spec/07 item 3: 3 to 5): every niche as a checkbox, children under their
 * parent. The count is announced as it changes; saving sends the whole list (PUT /api/me/niches), so the list can
 * change but never be cleared. A count outside the range is caught before sending, and the API's refusals
 * (`liked_niches_count`, `unknown_niche`) are fixed sentences. "Save niches" is the page's one primary action.
 */
export function NichePicker({ niches, initial, min, max, saveImpl = saveNiches }: NichePickerProps) {
  const t = useStrings("likedNiches");
  const [chosen, setChosen] = useState<string[]>(initial);
  const [saved, setSaved] = useState<string[]>(initial);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [issue, setIssue] = useState<CountIssue | null>(null);
  const alert = useRef<HTMLDivElement>(null);
  const fieldset = useRef<HTMLFieldSetElement>(null);

  function change(id: string) {
    const next = toggle(chosen, id);
    setChosen(next);
    // A count issue already shown clears as soon as the count is right again; a new one waits for "Save".
    if (issue && !countIssue(next.length, min, max)) setIssue(null);
    if (status.kind === "saved" || status.kind === "refused") setStatus({ kind: "idle" });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status.kind === "saving") return;
    const found = countIssue(chosen.length, min, max);
    if (found) {
      setIssue(found);
      fieldset.current?.querySelector<HTMLInputElement>("input")?.focus();
      return;
    }
    setIssue(null);
    setStatus({ kind: "saving" });
    const outcome = await saveImpl(chosen);
    if (outcome.ok) {
      const ids = outcome.value.liked.map((niche) => niche.id);
      setSaved(ids);
      if (!sameIds(ids, chosen)) setChosen(ids);
      setStatus({ kind: "saved" });
    } else {
      setStatus({ kind: "refused", problem: outcome.problem });
      // The alert is announced (role="alert"); focus goes to it so keyboard users land on the reason.
      requestAnimationFrame(() => alert.current?.focus());
    }
  }

  const unchanged = sameIds(chosen, saved) && saved.length > 0;
  const issueId = "liked-niches-issue";

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-6">
      <fieldset ref={fieldset} aria-describedby={`liked-niches-count${issue ? ` ${issueId}` : ""}`} className="min-w-0">
        <legend className="font-semibold text-ink">{t("legend")}</legend>
        <p id="liked-niches-count" aria-live="polite" className="mt-1 text-sm text-ink-soft">
          {t("chosen", { count: chosen.length, max })}
        </p>
        {issue ? (
          <div className="mt-2" role="alert">
            <FieldError id={issueId}>{issue === "tooFew" ? t("tooFew", { count: min }) : t("tooMany", { max })}</FieldError>
          </div>
        ) : null}
        <ul className="mt-3 sm:columns-2 sm:gap-10">
          {niches.map((parent) => (
            <li key={parent.id} className="break-inside-avoid">
              <Checkbox
                id={`niche-${parent.id}`}
                label={parent.name}
                checked={chosen.includes(parent.id)}
                onChange={() => change(parent.id)}
              />
              {parent.children.length > 0 ? (
                <ul className="border-l border-line pl-4 ml-2.5">
                  {parent.children.map((child) => (
                    <li key={child.id}>
                      <Checkbox
                        id={`niche-${child.id}`}
                        label={child.name}
                        checked={chosen.includes(child.id)}
                        onChange={() => change(child.id)}
                      />
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      </fieldset>

      {status.kind === "refused" ? (
        <Alert ref={alert}>
          {status.problem === "count" ? t("problem.count", { count: min, max }) : t(`problem.${status.problem}`)}
        </Alert>
      ) : null}
      {status.kind === "saved" && unchanged ? <Alert tone="ok">{t("saved")}</Alert> : null}

      <div>
        <Button type="submit" variant="primary" busy={status.kind === "saving"}>
          {status.kind === "saving" ? t("saving") : t("save")}
        </Button>
      </div>
    </form>
  );
}
