"use client";

import { useSyncExternalStore } from "react";

import { useStrings } from "./ClientStrings";
import { install, installOffered, subscribeInstall } from "./offline/install";
import { SignOutButton } from "./SignOutButton";
import { ThemeToggle } from "./ThemeToggle";

/**
 * The account menu's lower part (components/AccountMenu.tsx): "Install Wazo" where the browser offered it (P27), the
 * appearance switch and Sign out, a chunk of its own loaded with the menu's first opening (P25: the shell's script stays
 * under the 150 KB budget per route).
 */
export function AccountMenuExtras() {
  const t = useStrings("shell");
  // beforeinstallprompt, kept by the offline island (components/offline/Register.tsx) on the pages that carry it.
  const installable = useSyncExternalStore(subscribeInstall, installOffered, () => false);
  return (
    <>
      {installable ? (
        <div className="mt-1 border-t border-line pt-1">
          <button
            type="button"
            data-install=""
            className="flex min-h-11 w-full items-center rounded-control px-3 font-medium text-ink hover:bg-accent-wash"
            onClick={() => void install()}
          >
            {t("install", { product: t("workingName") })}
          </button>
        </div>
      ) : null}
      <div className="mt-1 border-t border-line px-1 pt-2 pb-1">
        <p className="px-2 text-xs font-medium text-ink-soft">{t("theme.label")}</p>
        <ThemeToggle className="mt-1" />
      </div>
      {/* Sign out reads as a menu item like the links above it; its failure notice stays under it. */}
      <div
        className={
          "mt-1 flex border-t border-line pt-1 [&>div]:w-full [&>div]:items-stretch [&>div>p]:px-3 [&>div>p]:text-left " +
          "[&_button]:w-full [&_button]:justify-start [&_button]:rounded-control [&_button]:px-3 [&_button]:text-ink " +
          "[&_button]:font-medium [&_button]:no-underline [&_button:hover]:bg-accent-wash [&_button:hover]:text-ink"
        }
      >
        <SignOutButton />
      </div>
    </>
  );
}
