"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { textLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Field } from "@/components/ui/Field";
import { Form, SubmitButton } from "@/components/ui/Form";
import { AlertIcon, CheckIcon } from "@/components/ui/icons";

import type { UploadCheck } from "./certificate";
import { Fingerprint } from "./Fingerprint";
import { checkFile, fileProblem, type FileProblem } from "./upload";

type State =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "done"; result: UploadCheck }
  | { kind: "problem"; problem: FileProblem };

const FIELD_PROBLEMS: ReadonlySet<FileProblem> = new Set(["noFile", "tooLarge"]);

export interface FileCheckProps {
  /** Check against this certificate only; without it the file is matched against every registered record. */
  certId?: string;
  /** The screen's one primary action (the certificate page); a secondary button on /verify. */
  primary?: boolean;
  checkFileImpl?: typeof checkFile;
}

/**
 * "Check a file": choose the manifest the owner shared, send its bytes to POST /api/verify and show match or no
 * match with the file's own fingerprint, so the two can be compared by eye. Nothing is read or shown from the file
 * but its fingerprint.
 */
export function FileCheck({ certId, primary = false, checkFileImpl = checkFile }: FileCheckProps) {
  const t = useTranslations("verifyFile");
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>({ kind: "idle" });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.kind === "busy") return;
    const file = input.current?.files?.[0];
    const early = fileProblem(file);
    if (early || !file) {
      setState({ kind: "problem", problem: early ?? "noFile" });
      input.current?.focus();
      return;
    }
    setState({ kind: "busy" });
    const outcome = await checkFileImpl(file, certId);
    setState(outcome.ok ? { kind: "done", result: outcome.result } : { kind: "problem", problem: outcome.problem });
  }

  const fieldProblem = state.kind === "problem" && FIELD_PROBLEMS.has(state.problem) ? state.problem : null;
  const formProblem = state.kind === "problem" && !FIELD_PROBLEMS.has(state.problem) ? state.problem : null;
  const headingId = `${id}-title`;

  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="text-lg text-ink">
        {t("title")}
      </h2>
      <p className="mt-2 max-w-[62ch] text-ink-soft">{certId ? t("leadThis") : t("leadAny")}</p>
      <Form onSubmit={submit} className="mt-5 flex flex-col gap-5" aria-labelledby={headingId}>
        {formProblem ? <Alert>{t(formProblem)}</Alert> : null}
        <Field id={`${id}-file`} label={t("label")} hint={t("hint")} error={fieldProblem ? t(fieldProblem) : undefined}>
          {(control) => (
            <input
              ref={input}
              type="file"
              name="file"
              onChange={() => setState({ kind: "idle" })}
              className={cn(
                "w-full min-w-0 text-base text-ink",
                "file:mr-4 file:min-h-11 file:cursor-pointer file:rounded-control file:border file:border-ink-soft",
                "file:bg-field file:px-4 file:text-base file:font-semibold file:text-ink hover:file:bg-jacaranda-wash",
              )}
              {...control}
            />
          )}
        </Field>
        <div>
          <SubmitButton variant={primary ? "primary" : "secondary"} busy={state.kind === "busy"}>
            {state.kind === "busy" ? t("checking") : t("submit")}
          </SubmitButton>
        </div>
      </Form>
      <div role="status" className="mt-6 empty:hidden">
        {state.kind === "done" ? <Result result={state.result} certId={certId} /> : null}
      </div>
    </section>
  );
}

function Result({ result, certId }: { result: UploadCheck; certId?: string }) {
  const t = useTranslations("verifyFile");
  const matched = result.match;
  const found = result.certificate?.cert_id;
  const message = matched
    ? certId
      ? t("matchThis")
      : t("match", { certId: found ?? "" })
    : certId
      ? t("noMatchThis")
      : t("noMatch");
  return (
    <div className={cn("border-l-4 pl-4 sm:pl-6", matched ? "border-ok" : "border-error")}>
      <p className={cn("flex items-start gap-2 font-semibold", matched ? "text-ok" : "text-error")}>
        {matched ? <CheckIcon className="mt-0.5 size-5 shrink-0" /> : <AlertIcon className="mt-0.5 size-5 shrink-0" />}
        <span data-testid="file-result">{message}</span>
      </p>
      <p className="mt-4 text-sm font-medium text-ink-soft">{t("yourHash")}</p>
      <Fingerprint hex={result.content_hash} className="mt-1" />
      {matched && found && !certId ? (
        <Link href={`/verify/${encodeURIComponent(found)}`} className={cn(textLinkClass, "mt-2 inline-block")}>
          {t("view", { certId: found })}
        </Link>
      ) : null}
    </div>
  );
}
