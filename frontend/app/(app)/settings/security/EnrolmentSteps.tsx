"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { encode } from "uqr";

import { QrCode } from "@/components/QrCode";
import { Alert } from "@/components/ui/Alert";
import { Form, SubmitButton } from "@/components/ui/Form";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon } from "@/components/ui/icons";
import { OtpInput } from "@/components/ui/OtpInput";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

import { ErrorNotice } from "./ErrorNotice";
import { reveal } from "./reveal";
import { Steps } from "./Steps";

// Loaded only after POST /api/auth/totp/enrol succeeds (React.lazy, see lazy.ts), with the QR encoder, so none of
// this is in the page's first download (docs/spec/07 item 5: 150 KB, i.e. 150,000 bytes, of gzipped JS per route).

type Notice = "keyCopied" | "codesCopied" | "copyFailed" | null;

/** How long "Cancel setup" waits for the server to say whether two-step sign-in is on before saying it cannot tell. */
const STATUS_CHECK_MS = 10_000;

/**
 * Whether two-step sign-in is on at the server (GET /api/auth/me), or null when that cannot be told: offline, an
 * error, the session ended, or no answer in time.
 */
async function enrolledOnServer(): Promise<boolean | null> {
  const outcome = await settle(api.GET("/api/auth/me", { signal: AbortSignal.timeout(STATUS_CHECK_MS) }));
  return outcome.ok ? outcome.data.mfa.enrolled : null;
}

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
  /** The name the authenticator app lists the entry under (the setup key's issuer, else the product name). */
  entryName: string;
  /** The server lost the pending enrolment (no_pending_enrolment) and two-step sign-in is off: back to the start. */
  onRestart: (error: ErrorKey) => void;
  /** "Cancel setup", with two-step sign-in known to be off: back to the start. */
  onCancel: () => void;
  /** Two-step sign-in is on at the server, but the answer with the recovery codes never arrived. */
  onEnrolled: () => void;
}

/** Steps 1-3 after enrolment starts: QR and key, confirm a code, then the ten recovery codes shown once. */
export function EnrolmentSteps({
  secret,
  otpauthUri,
  homeHref,
  entryName,
  onRestart,
  onCancel,
  onEnrolled,
}: EnrolmentStepsProps) {
  const t = useTranslations("security");
  const tv = useTranslations("validation");
  const te = useTranslations("errors");
  const router = useRouter();
  const heading = useRef<HTMLHeadingElement>(null);
  // The notices show above the steps, far above the buttons that lead to them (at 360 px, over 400 px up).
  const statusRef = useRef<HTMLDivElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const qr = useMemo(() => qrMatrix(otpauthUri), [otpauthUri]);

  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [codeFocused, setCodeFocused] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusUnknown, setStatusUnknown] = useState(false);
  // Set once a confirmation fails other than with a wrong code. Past the code check the server commits in one go
  // (two-step sign-in on, recovery codes made, the "turned on" email queued), and a lost answer (offline, a reset
  // connection), a 5xx or a proxy timeout can come after that commit. From then on, the page asks the server before
  // it says setup was cancelled: "delete that entry" to someone whose two-step sign-in is on, with recovery codes
  // they never saw, locks them out at the next sign-in. It stays set: a later wrong-code answer does not prove the
  // earlier try failed.
  const maybeOn = useRef(false);

  const current = codes ? 3 : codeFocused ? 2 : 1;
  // Steps 1 and 2 count as done only once the code is confirmed, not because the code field has focus.
  const done = codes ? 2 : 0;

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
    setStatusUnknown(false);
    const outcome = await settle(api.POST("/api/auth/totp/confirm", { body: { code } }));
    if (outcome.ok) {
      setBusy(false);
      setNotice(null);
      setCodes(outcome.data.recovery_codes);
      return;
    }
    if (outcome.key === "invalid_code") {
      setBusy(false);
      setCode("");
      setCodeError(te("invalid_code"));
      document.getElementById("totp-code")?.focus();
      return;
    }
    maybeOn.current = true;
    if (outcome.key === "no_pending_enrolment") {
      // No setup is waiting: it was replaced, or an earlier try whose answer was lost turned two-step sign-in on.
      await askServer(() => onRestart("no_pending_enrolment"));
      return;
    }
    // The error shows above the steps, out of sight from the Confirm button at 360 px: focus brings it into view.
    reveal(
      () => {
        setBusy(false);
        setError(outcome.key);
      },
      () => errorRef.current,
    );
  }

  /**
   * Asks the server whether two-step sign-in is on (busy meanwhile, so neither Confirm nor Cancel acts): on goes to
   * the "on" screen, off goes on with `whenOff`, and no answer keeps these steps with a hint to reload, focused.
   */
  async function askServer(whenOff: () => void) {
    const enrolled = await enrolledOnServer();
    if (enrolled === null) {
      reveal(
        () => {
          setBusy(false);
          setStatusUnknown(true);
        },
        () => statusRef.current,
      );
      return;
    }
    setBusy(false);
    if (enrolled) onEnrolled();
    else whenOff();
  }

  async function cancel() {
    if (busy) return;
    if (!maybeOn.current) {
      onCancel(); // only wrong codes so far, or no try: nothing was turned on
      return;
    }
    setBusy(true);
    setError(null);
    setStatusUnknown(false);
    await askServer(onCancel);
  }

  const noticeLine = (
    <p role="status" className="min-h-6 text-sm font-medium text-ink-soft">
      {notice ? (
        <span className={cn("inline-flex items-center gap-1.5", notice === "copyFailed" ? "text-error" : "text-ok")}>
          {notice === "copyFailed" ? <AlertIcon className="size-5" /> : <CheckIcon className="size-5" />}
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
      {statusUnknown ? <Alert ref={statusRef}>{t("statusUnknown", { product: entryName })}</Alert> : null}
      <ErrorNotice error={error} alertRef={errorRef} />
      <Steps
        // The recovery codes are a new stage, not a moved one: a new list replaces the setup list, focus goes to its
        // current heading, and step 3 does not slide up into the space steps 1-2 leave (a 0.94 layout shift at
        // 360 px when a slow confirmation answered).
        key={codes ? "codes" : "setup"}
        label={t("stepsLabel")}
        doneLabel={t("stepDone")}
        current={current}
        done={done}
        currentHeadingRef={heading}
        steps={[
          { title: t("step1"), body: codes ? null : setupBody },
          { title: t("step2"), body: codes ? null : confirmBody },
          { title: t("step3"), body: codesBody },
        ]}
      />
      {codes ? null : (
        // Once the code is confirmed, two-step sign-in is on: nothing is left to cancel. While a code or the status is
        // being checked, cancelling could hide a success, so the button waits (busy ignores presses).
        <div>
          <Button variant="link" busy={busy} onClick={cancel}>
            {t("cancelSetup")}
          </Button>
        </div>
      )}
    </div>
  );
}
