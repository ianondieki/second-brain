"use client";

import { useStrings } from "@/components/ClientStrings";
import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon } from "@/components/ui/status-icons";

function download(codes: string[]) {
  const url = URL.createObjectURL(new Blob([`${codes.join("\n")}\n`], { type: "text/plain" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "recovery-codes.txt";
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * Ten recovery codes, shown once: at the end of setup and after "Get new recovery codes". The codes live only in
 * the component's props (never stored in the browser); copy and download are the ways to keep them.
 *
 * Leaving the page removes them from it: the back-forward cache keeps a page as it was at `pagehide`, so Back (or
 * someone else at the same browser) would otherwise bring them back after a full navigation away. The list is
 * cleared synchronously in `pagehide`, before the page is frozen, and again on a `pageshow` from the cache.
 */
export function RecoveryCodeList({ codes }: { codes: string[] }) {
  const t = useStrings("security");
  const [notice, setNotice] = useState<"codesCopied" | "copyFailed" | null>(null);
  const [cleared, setCleared] = useState(false);

  useEffect(() => {
    const clear = () => flushSync(() => setCleared(true));
    const restored = (event: PageTransitionEvent) => {
      if (event.persisted) clear();
    };
    window.addEventListener("pagehide", clear);
    window.addEventListener("pageshow", restored);
    return () => {
      window.removeEventListener("pagehide", clear);
      window.removeEventListener("pageshow", restored);
    };
  }, []);

  if (cleared) {
    return (
      <p data-testid="recovery-codes-cleared" className="text-ink-soft">
        {t("codesCleared")}
      </p>
    );
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      setNotice("codesCopied");
    } catch {
      setNotice("copyFailed");
    }
  }

  return (
    <>
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
      <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
        <Button variant="secondary" className="w-full sm:w-auto" onClick={copy}>
          {t("copyCodes")}
        </Button>
        <Button variant="secondary" className="w-full sm:w-auto" onClick={() => download(codes)}>
          {t("download")}
        </Button>
      </div>
      <p role="status" className="min-h-6 text-sm font-medium text-ink-soft">
        {notice ? (
          <span className={cn("inline-flex items-center gap-1.5", notice === "copyFailed" ? "text-error" : "text-ok")}>
            {notice === "copyFailed" ? <AlertIcon className="size-5" /> : <CheckIcon className="size-5" />}
            {t(notice)}
          </span>
        ) : null}
      </p>
    </>
  );
}
