import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { formatMoment } from "@/lib/format";

import { accountHash } from "../palette/PaletteSlot";
import { cn } from "../ui/cn";
import { noticeBox, noticeTone } from "../ui/notice";
import { Icon } from "../ui/status-icons";

import { Register } from "./Register";

/**
 * This build's id (`.next/BUILD_ID`, written by `next build`), which versions the service worker (`/sw.js?v=`): a new
 * build installs a new worker, which drops the old build's files and pages. "dev" where there is none (`next dev`).
 */
export function readBuildVersion(read: (path: string) => string = (path) => readFileSync(path, "utf8")): string {
  try {
    return read(join(process.cwd(), ".next", "BUILD_ID")).trim() || "dev";
  } catch {
    return "dev";
  }
}

let build: string | undefined;
/** The build's id, read once per server process. */
export function buildVersion(): string {
  build ??= readBuildVersion();
  return build;
}

function OfflineIcon() {
  return (
    <Icon className="mt-0.5 size-5 shrink-0 text-accent">
      <path d="M2.5 7.5a11 11 0 0 1 4.2-2.6M17.5 7.5A11 11 0 0 0 10 4.5" />
      <path d="M5.25 10.6a6.6 6.6 0 0 1 2.2-1.35M14.75 10.6A6.6 6.6 0 0 0 11.8 9" />
      <path d="M10 14.5v.05" strokeWidth="2.25" />
      <path d="m3 3 14 14" />
    </Icon>
  );
}

/**
 * The offline banner, drawn by the server with every page that carries it and hidden until the page is read offline
 * (globals.css: shown only under <html data-offline>, which Register sets): "This is {page} as of {time} EAT", the time this
 * very answer was made, which is the cached copy's Date when the worker serves it later. No script of its own.
 */
export async function OfflineBanner({ page, at = new Date() }: { page: string; at?: Date }) {
  const [t, locale] = await Promise.all([getTranslations("offline"), getLocale()]);
  return (
    <div role="status" data-offline-banner="" className={cn(noticeBox, noticeTone.info, "mb-6 max-w-3xl")}>
      <OfflineIcon />
      <p className="min-w-0 flex-1">{t("banner", { page, time: formatMoment(locale, at.toISOString()) })}</p>
    </div>
  );
}

async function Island() {
  return <Register hash={await accountHash()} version={buildVersion()} />;
}

/**
 * The offline part of the signed-in shell (P27 track F; D-69), for SignedInShell's `offline` prop: the banner (hidden
 * until offline) and the island with the signed-in person's hash (the command palette's, never the id) and the build.
 * Given by both Homes (where a person lands on signing in, so another person's cache goes at once), both Engagements
 * lists and both trackers (the pages the worker keeps); `page` is what the banner calls the page. Never in the staff
 * console (SignedInShell leaves it out there). The island streams: it never holds the page.
 */
export function OfflineSlot({ page }: { page: string }) {
  return (
    <>
      <OfflineBanner page={page} />
      {/* The worker in production builds only: `next dev` serves files that change under the same names. */}
      {process.env.NODE_ENV === "production" ? (
        <Suspense fallback={null}>
          <Island />
        </Suspense>
      ) : null}
    </>
  );
}
