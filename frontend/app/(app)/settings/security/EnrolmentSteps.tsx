"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { encode } from "uqr";

import { QrCode } from "@/components/QrCode";
import { Form, SubmitButton } from "@/components/ui/Form";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { CheckIcon, InfoIcon } from "@/components/ui/icons";
import { OtpInput } from "@/components/ui/OtpInput";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

import { Steps } from "./Steps";

// Loaded only after POST /api/auth/totp/enrol succeeds (next/dynamic in SecuritySettings), with the QR encoder, so
// none of this is in the page's first download (docs/spec/07 item 5: 150 KiB of gzipped JS per route).

type Notice = "keyCopied" | "codesCopied" | "copyFailed" | null;

/** "ABCDEFGHIJKL" -> ["ABCD", "EFGH", "IJKL"]: easier to type into an authenticator app by hand. */
function keyGroups(secret: string) {
  return secret.match(/.{1,4}/g) ?? [secret];
}

function qrMatrix(uri: string): boolean[][] | null {
  try {
    return encode(uri, { ecc: "M", border: 0 }).data;
  } catch {
    return null; // the key below still works without the picture
  }
}

function download(codes: string[]) {
  const url = URL.createObjectURL(new Blob([`${codes.join("\n")}\n`], { type: "text/plain" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "recovery-codes.txt";
  anchor.click();
  URL.revokeObjectURL(url);
}

export interface EnrolmentStepsProps {
  secret: string;
  otpauthUri: string;
  homeHref: string;
  /** The server lost the pending enrolment (no_pending_enrolment): go back to the start. */
  onRestart: (error: ErrorKey) => void;
}

/** Steps 1-3 after enrolment starts: QR and key, confirm a code, then the ten recovery codes shown once. */
export function EnrolmentSteps({ secret, otpauthUri, homeHref, onRestart }: EnrolmentStepsProps) {
  const t = useTranslations("security");
  const tv = useTranslations("validation");
  const te = useTranslations("errors");
  const router = useRouter();
  const heading = useRef<HTMLHeadingElement>(null);
  const qr = useMemo(() => qrMatrix(otpauthUri), [otpauthUri]);

  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [codeFocused, setCodeFocused] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [busy, setBusy] = useState(false);

  const current = codes ? 3 : codeFocused ? 2 : 1;

  // Arriving here (and reaching the codes) moves focus to the current step, so screen readers follow the change.
  useEffect(() => {
    heading.current?.focus();
  }, [codes]);

  async function copy(text: string, done: Exclude<Notice, "copyFailed" | null>) {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(done);
    } catch {
      setNotice("copyFailed");
    }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (code.length !== 6) {
      setCodeError(tv("code"));
      document.getElementById("totp-code")?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const outcome = await settle(api.POST("/api/auth/totp/confirm", { body: { code } }));
    setBusy(false);
    if (outcome.ok) {
      setNotice(null);
      setCodes(outcome.data.recovery_codes);
      return;
    }
    if (outcome.key === "invalid_code") {
      setCode("");
      setCodeError(te("invalid_code"));
      document.getElementById("totp-code")?.focus();
      return;
    }
    if (outcome.key === "no_pending_enrolment") {
      onRestart(outcome.key);
      return;
    }
    setError(outcome.key);
  }

  const noticeLine = (
    <p role="status" className="min-h-6 text-sm font-medium text-ink-soft">
      {notice ? (
        <span className={cn("inline-flex items-center gap-1.5", notice === "copyFailed" ? "text-error" : "text-ok")}>
          {notice === "copyFailed" ? <InfoIcon className="size-5" /> : <CheckIcon className="size-5" />}
          {t(notice)}
        </span>
      ) : null}
    </p>
  );

  const setupBody = (
    <div className="flex flex-col gap-5">
      <p className="text-ink-soft">{t("step1Body")}</p>
      {qr ? <QrCode matrix={qr} label={t("qrLabel")} /> : null}
      <dl className="flex flex-col gap-1">
        <dt className="font-medium text-ink">{t("key")}</dt>
        <dd data-testid="totp-key" className="code-figures text-base font-semibold text-ink sm:text-lg">
          {/* Wraps only between groups of four, never inside one. */}
          {keyGroups(secret).map((group, index) => (
            <Fragment key={index}>
              {index > 0 ? " " : null}
              <span className="whitespace-nowrap">{group}</span>
            </Fragment>
          ))}
        </dd>
      </dl>
      <div className="flex flex-col items-start gap-1">
        <Button variant="secondary" onClick={() => copy(secret, "keyCopied")}>
          {t("copyKey")}
        </Button>
        {noticeLine}
      </div>
    </div>
  );

  const confirmBody = (
    <Form onSubmit={confirm} className="flex flex-col items-start gap-5">
      <OtpInput
        id="totp-code"
        name="code"
        label={t("code")}
        value={code}
        onChange={(value) => {
          setCode(value);
          setCodeError(undefined);
        }}
        onFocus={() => setCodeFocused(true)}
        error={codeError}
      />
      <SubmitButton variant="primary" busy={busy}>
        {busy ? t("confirming") : t("confirm")}
      </SubmitButton>
    </Form>
  );

  const codesBody = codes ? (
    <div className="flex flex-col items-start gap-5">
      <p className="text-ink-soft">{t("codesLead")}</p>
      <div className="w-full">
        <h4 id="codes-label" className="text-base font-medium">
          {t("codesLabel")}
        </h4>
        <ul
          aria-labelledby="codes-label"
          data-testid="recovery-codes"
          className={
            "code-figures mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 " + // ten codes: five even rows
            "border border-line bg-field px-4 py-3 text-base font-semibold text-ink sm:text-lg"
          }
        >
          {codes.map((recovery) => (
            <li key={recovery} className="whitespace-nowrap">
              {recovery}
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button variant="secondary" onClick={() => copy(codes.join("\n"), "codesCopied")}>
          {t("copyCodes")}
        </Button>
        <Button variant="secondary" onClick={() => download(codes)}>
          {t("download")}
        </Button>
      </div>
      {noticeLine}
      <Button variant="primary" onClick={() => router.push(homeHref)}>
        {t("done")}
      </Button>
    </div>
  ) : null;

  return (
    <div className="flex flex-col gap-6">
      {error ? <Alert>{te(error)}</Alert> : null}
      <Steps
        label={t("stepsLabel")}
        doneLabel={t("stepDone")}
        current={current}
        currentHeadingRef={heading}
        steps={[
          { title: t("step1"), body: codes ? null : setupBody },
          { title: t("step2"), body: codes ? null : confirmBody },
          { title: t("step3"), body: codesBody },
        ]}
      />
    </div>
  );
}
