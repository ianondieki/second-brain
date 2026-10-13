import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { standaloneLinkClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { cn } from "@/components/ui/cn";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { EmptyState } from "@/components/ui/EmptyState";
import { ClosedIcon } from "@/components/ui/icons";
import { Lattice } from "@/components/ui/Lattice";
import { CheckIcon } from "@/components/ui/status-icons";
import { formatCalendarDate, formatDay, formatMoment } from "@/lib/format";

import { KEYS_HREF } from "../verify/certificate";
import { Fingerprint } from "../verify/Fingerprint";

import { keyAnchor, ROOT_MESSAGE, ROOTS_HREF, type ProvenanceKey, type TransparencyRead, type TransparencyRoot } from "./transparency";

type T = Awaited<ReturnType<typeof getTranslations<"transparency">>>;

const inlineLinkClass = "font-semibold text-ink underline decoration-1 underline-offset-2 hover:decoration-2";
const hashClass = "font-mono text-sm leading-6 text-ink [overflow-wrap:anywhere]";

/**
 * Public /transparency (REQ-AUD-01; P28 track D), drawn on the server with no script of its own: what the daily roots
 * are and how a person checks a certificate (a link to /verify); the latest root as the page's one sheet (the
 * certificate's lattice edge, the root in the fingerprint well, its key and signature); the earlier days as a quiet
 * ledger, newest first; then the signing keys with their status. No root yet is one sentence and one action; a read
 * that failed is one sentence and "Try again", for its part only.
 */
export async function TransparencyContent({ roots, keys }: TransparencyRead) {
  const [t, locale] = await Promise.all([getTranslations("transparency"), getLocale()]);
  const [latest, ...earlier] = roots ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-10 pb-20 sm:px-6 lg:pt-16 lg:pb-28">
      <h1 className="text-[2.25rem] leading-[1.05] text-ink [overflow-wrap:anywhere] lg:text-[3.25rem]">{t("title")}</h1>
      <p className="mt-4 max-w-[60ch] text-lg text-ink-soft">{t("lead")}</p>
      <p className="mt-3 max-w-[60ch] text-ink-soft" data-transparency="how-to">
        {t.rich("howTo", {
          link: (chunks) => (
            <Link href="/verify" className={inlineLinkClass}>
              {chunks}
            </Link>
          ),
        })}
      </p>

      <div className="mt-10" data-transparency="roots">
        {roots === null ? (
          <EmptyState sentence={t("unavailable")} action={t("retry")} href="/transparency" />
        ) : latest === undefined ? (
          <EmptyState sentence={t("empty")} action={t("emptyAction")} href="/verify" />
        ) : (
          <>
            <LatestRoot root={latest} t={t} locale={locale} />
            {earlier.length > 0 ? (
              <section aria-labelledby="earlier-days" className="mt-12">
                <h2 id="earlier-days" className="text-xl text-ink">
                  {t("earlierTitle")}
                </h2>
                <ol className="mt-4 flex flex-col divide-y divide-line border-y border-line" data-transparency="earlier">
                  {earlier.map((root) => (
                    <EarlierRoot key={root.day} root={root} t={t} locale={locale} />
                  ))}
                </ol>
              </section>
            ) : null}
            <p className="mt-6">
              <a href={ROOTS_HREF} className={standaloneLinkClass}>
                {t("rootsJson")}
              </a>
            </p>
          </>
        )}
      </div>

      <section aria-labelledby="signing-keys" className="mt-14" data-transparency="keys">
        <h2 id="signing-keys" className="text-xl text-ink">
          {t("keysTitle")}
        </h2>
        <p className="mt-2 max-w-[62ch] text-ink-soft">
          {t.rich("keysLead", {
            message: ROOT_MESSAGE,
            code: (chunks) => <code className="font-mono text-sm text-ink [overflow-wrap:anywhere]">{chunks}</code>,
          })}
        </p>
        {keys === null ? (
          <EmptyState className="mt-6" sentence={t("keysUnavailable")} action={t("retry")} href="/transparency" />
        ) : keys.length === 0 ? (
          <EmptyState className="mt-6" sentence={t("keysEmpty")} action={t("emptyAction")} href="/verify" />
        ) : (
          <>
            <ul className="mt-6 flex flex-col divide-y divide-line border-y border-line">
              {keys.map((key) => (
                <KeyRow key={key.kid} signingKey={key} t={t} locale={locale} />
              ))}
            </ul>
            <p className="mt-6">
              <a href={KEYS_HREF} className={standaloneLinkClass}>
                {t("keysJson")}
              </a>
            </p>
          </>
        )}
      </section>
    </div>
  );
}

/** The latest root as a signed sheet: its day in the heading, the time it covers, the root, its key and signature. */
function LatestRoot({ root, t, locale }: { root: TransparencyRoot; t: T; locale: string }) {
  return (
    <Card as="section" padding="none" aria-labelledby="latest-root" className="overflow-hidden" data-root={root.day}>
      <Lattice />
      <div className="p-5 sm:p-8">
        <h2 id="latest-root" className="text-2xl text-ink [overflow-wrap:anywhere]">
          {t("latestTitle", { day: formatCalendarDate(locale, root.day) })}
        </h2>
        <p className="mt-2 max-w-[56ch] text-ink-soft">
          {root.snapshot_at ? t("covers", { time: formatMoment(locale, root.snapshot_at) }) : t("coversUnknown")}
        </p>
        <h3 className="mt-6 text-sm font-medium text-ink-soft">{t("root")}</h3>
        <div className="mt-2 rounded-control border border-line bg-paper px-4 py-3">
          <Fingerprint hex={root.merkle_root} />
        </div>
        <DescriptionList className="mt-6">
          <Description label={t("key")}>
            <KeyLink kid={root.key_id} />
          </Description>
          <Description label={t("signature")}>
            <Code className="text-sm text-ink-soft">{root.signature}</Code>
          </Description>
        </DescriptionList>
      </div>
      <Lattice />
    </Card>
  );
}

/** An earlier day: its date, the root, when the snapshot was taken and by which key it was signed; the signature folded. */
function EarlierRoot({ root, t, locale }: { root: TransparencyRoot; t: T; locale: string }) {
  const key = (chunks: ReactNode) => <KeyLink kid={root.key_id}>{chunks}</KeyLink>;
  return (
    <li className="py-5" data-root={root.day}>
      <h3 className="font-sans text-base font-semibold text-ink">
        <time dateTime={root.day}>{formatCalendarDate(locale, root.day)}</time>
      </h3>
      <p className={cn(hashClass, "mt-1")} data-merkle-root={root.merkle_root}>
        {root.merkle_root}
      </p>
      <p className="mt-1 text-sm text-ink-soft">
        {root.snapshot_at
          ? t.rich("earlierLine", { time: formatMoment(locale, root.snapshot_at), keyId: root.key_id, key })
          : t.rich("earlierLineUnknown", { keyId: root.key_id, key })}
      </p>
      {/* Native disclosure: no script, and the signature (88 characters) stays out of the way until asked for. */}
      <details className="group mt-1">
        <summary className="inline-flex min-h-11 cursor-pointer items-center text-sm font-semibold text-ink underline decoration-1 underline-offset-2 hover:decoration-2">
          {t("showSignature")}
        </summary>
        <Code className="pb-2 text-sm text-ink-soft">{root.signature}</Code>
      </details>
    </li>
  );
}

/** One signing key: its id (the anchor a root's key id links to), its status as icon and words, then its facts. */
function KeyRow({ signingKey, t, locale }: { signingKey: ProvenanceKey; t: T; locale: string }) {
  const retired = signingKey.retired_at;
  return (
    <li id={keyAnchor(signingKey.kid)} className="scroll-mt-24 py-5" data-key={signingKey.kid}>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <h3 className="min-w-0 font-mono text-base font-semibold text-ink [overflow-wrap:anywhere]">{signingKey.kid}</h3>
        <p className="flex items-center gap-2 text-sm font-semibold" data-key-status={retired ? "retired" : "active"}>
          {retired ? (
            <ClosedIcon className="size-4 shrink-0 text-ink-soft" />
          ) : (
            <CheckIcon className="size-4 shrink-0 text-accent" />
          )}
          <span className={retired ? "text-ink-soft" : "text-ink"}>
            {retired ? t("keyRetired", { date: formatDay(locale, retired) }) : t("keyActive")}
          </span>
        </p>
      </div>
      <DescriptionList dense className="mt-3">
        <Description label={t("algorithm")}>{t("algorithmEd25519")}</Description>
        <Description label={t("added")}>
          <time dateTime={signingKey.created_at}>{formatDay(locale, signingKey.created_at)}</time>
        </Description>
        <Description label={t("publicKey")}>
          <pre className="font-mono text-sm leading-6 whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">{signingKey.pem.trim()}</pre>
        </Description>
      </DescriptionList>
    </li>
  );
}

/** A key id as a link to its entry in the keys list below. */
function KeyLink({ kid, children }: { kid: string; children?: ReactNode }) {
  return (
    <a href={`#${keyAnchor(kid)}`} className="font-mono text-ink underline decoration-1 underline-offset-2 [overflow-wrap:anywhere] hover:decoration-2">
      {children ?? kid}
    </a>
  );
}

function Code({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("block font-mono [overflow-wrap:anywhere] text-ink", className)}>{children}</span>;
}
