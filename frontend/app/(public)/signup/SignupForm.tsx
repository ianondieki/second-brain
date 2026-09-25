"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button, textLinkClass } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { PasswordField } from "@/components/ui/PasswordField";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import { fieldForError, type ErrorKey } from "@/lib/api/errors";
import { rememberEmail } from "@/lib/auth/session";
import {
  ORG_KINDS,
  SIGNUP_FIELDS,
  validateSignup,
  type OrgKind,
  type SignupField,
  type SignupSide,
  type SignupValues,
} from "@/lib/auth/validation";

const CONSENTS = ["marketing", "reminders", "whatsapp", "profiling"] as const;
type Consent = (typeof CONSENTS)[number];
const CONSENT_LABEL = {
  marketing: "consentMarketing",
  reminders: "consentReminders",
  whatsapp: "consentWhatsapp",
  profiling: "consentProfiling",
} as const satisfies Record<Consent, string>;

/** Where focus goes for each field when it is the first one with an error. */
const FOCUS_ID: Record<SignupField, string> = {
  side: "side-developer",
  displayName: "display-name",
  email: "email",
  password: "password",
  orgName: "org-name",
  orgKind: "org-kind",
  terms: "terms",
};

const SERVER_FIELD: Partial<Record<string, SignupField>> = {
  email: "email",
  password: "password",
  terms: "terms",
  orgName: "orgName",
};

export function SignupForm() {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const summaryRef = useRef<HTMLDivElement>(null);

  const [values, setValues] = useState<SignupValues>({
    side: null,
    displayName: "",
    email: "",
    password: "",
    orgName: "",
    orgKind: "",
    terms: false,
  });
  const [consents, setConsents] = useState<Record<Consent, boolean>>({
    marketing: false,
    reminders: false,
    whatsapp: false,
    profiling: false,
  });
  const [errors, setErrors] = useState<Partial<Record<SignupField, string>>>({});
  const [serverError, setServerError] = useState<ErrorKey | null>(null);
  const [busy, setBusy] = useState(false);

  function set<K extends keyof SignupValues>(key: K, value: SignupValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
    if (errors[key]) {
      setErrors((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setServerError(null);

    const invalid = validateSignup(values);
    const messages: Partial<Record<SignupField, string>> = {};
    for (const field of SIGNUP_FIELDS) {
      const key = invalid[field];
      if (key) messages[field] = t(`validation.${key}`);
    }
    setErrors(messages);
    const first = SIGNUP_FIELDS.find((field) => messages[field]);
    if (first) {
      document.getElementById(FOCUS_ID[first])?.focus();
      return;
    }

    setBusy(true);
    const side = values.side as SignupSide;
    const outcome = await settle(
      api.POST("/api/auth/signup", {
        body: {
          side,
          display_name: values.displayName.trim(),
          email: values.email.trim(),
          password: values.password,
          org: side === "org" ? { legal_name: values.orgName.trim(), kind: values.orgKind as OrgKind } : null,
          consents: { ...consents },
          locale,
          accept_terms: values.terms,
        },
      }),
    );
    if (outcome.ok) {
      rememberEmail(values.email);
      router.push("/signup/check-email");
      return;
    }
    setBusy(false);
    setServerError(outcome.key);
    const errorField = fieldForError(outcome.key);
    const field = errorField ? SERVER_FIELD[errorField] : undefined;
    if (field) setErrors((current) => ({ ...current, [field]: t(`errors.${outcome.key}`) }));
    requestAnimationFrame(() => summaryRef.current?.focus());
  }

  return (
    <form noValidate onSubmit={submit} className="mt-8 flex flex-col gap-6">
      {serverError ? <Alert ref={summaryRef}>{t(`errors.${serverError}`)}</Alert> : null}

      <RadioGroup<SignupSide>
        id="side"
        name="side"
        legend={t("signup.sideLegend")}
        value={values.side}
        onChange={(side) => set("side", side)}
        error={errors.side}
        options={[
          { value: "developer", label: t("signup.sideDeveloper"), hint: t("signup.sideDeveloperHint") },
          { value: "org", label: t("signup.sideOrg"), hint: t("signup.sideOrgHint") },
        ]}
      />

      <TextField
        id="display-name"
        name="display_name"
        label={t("signup.displayName")}
        hint={t("signup.displayNameHint")}
        autoComplete="name"
        maxLength={120}
        value={values.displayName}
        onChange={(event) => set("displayName", event.target.value)}
        error={errors.displayName}
      />

      <TextField
        id="email"
        name="email"
        type="email"
        label={t("fields.email")}
        autoComplete="email"
        autoCapitalize="none"
        spellCheck={false}
        value={values.email}
        onChange={(event) => set("email", event.target.value)}
        error={errors.email}
      />

      <PasswordField
        id="password"
        name="password"
        label={t("fields.password")}
        hint={t("signup.passwordHint")}
        autoComplete="new-password"
        maxLength={128}
        value={values.password}
        onChange={(event) => set("password", event.target.value)}
        error={errors.password}
        showLabel={t("fields.showPassword")}
        hideLabel={t("fields.hidePassword")}
        showName={t("fields.showPasswordName")}
        hideName={t("fields.hidePasswordName")}
      />

      {values.side === "org" ? (
        <>
          <TextField
            id="org-name"
            name="org_name"
            label={t("signup.orgName")}
            hint={t("signup.orgNameHint")}
            autoComplete="organization"
            maxLength={200}
            value={values.orgName}
            onChange={(event) => set("orgName", event.target.value)}
            error={errors.orgName}
          />
          <SelectField
            id="org-kind"
            name="org_kind"
            label={t("signup.orgKind")}
            value={values.orgKind}
            onChange={(event) => set("orgKind", event.target.value as OrgKind | "")}
            error={errors.orgKind}
          >
            <option value="" disabled>
              {t("signup.orgKindPlaceholder")}
            </option>
            {ORG_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {t(`orgKind.${kind}`)}
              </option>
            ))}
          </SelectField>
        </>
      ) : null}

      <div className="border-t border-line pt-6">
        <fieldset aria-describedby="consents-hint" className="flex flex-col">
          <legend className="font-medium text-ink">{t("signup.consentsLegend")}</legend>
          <p id="consents-hint" className="mt-1 mb-1 text-sm text-ink-soft">
            {t("signup.consentsHint")}
          </p>
          {CONSENTS.map((purpose) => (
            <Checkbox
              key={purpose}
              id={`consent-${purpose}`}
              name={`consent_${purpose}`}
              label={t(`signup.${CONSENT_LABEL[purpose]}`)}
              checked={consents[purpose]}
              onChange={(event) => setConsents((current) => ({ ...current, [purpose]: event.target.checked }))}
            />
          ))}
        </fieldset>
      </div>

      <div className="border-t border-line pt-4">
        <Checkbox
          id="terms"
          name="accept_terms"
          checked={values.terms}
          onChange={(event) => set("terms", event.target.checked)}
          error={errors.terms}
          label={t.rich("signup.terms", {
            terms: (chunks) => (
              <Link href="/legal/terms" target="_blank" rel="noopener" className={textLinkClass}>
                {chunks}
              </Link>
            ),
            hint: (chunks) => <span className="sr-only">{chunks}</span>,
          })}
        />
      </div>

      <div className="flex flex-col items-start gap-4">
        <Button type="submit" variant="primary" busy={busy}>
          {busy ? t("signup.submitting") : t("signup.submit")}
        </Button>
        <p className="text-ink">
          {t.rich("signup.haveAccount", {
            login: (chunks) => (
              <Link href="/login" className={textLinkClass}>
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
    </form>
  );
}
