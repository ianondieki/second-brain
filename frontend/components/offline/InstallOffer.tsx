"use client";

import { useEffect } from "react";

import { dropInstallOffer, keepInstallOffer } from "./install";

/**
 * Keeps the browser's offer to install Wazo (`beforeinstallprompt`) for the account menu's "Install Wazo" (P27 track F).
 * On both Homes, where a person lands: the trackers carry only the offline script (the JS budget). Draws nothing.
 */
export function InstallOffer() {
  useEffect(() => {
    addEventListener("beforeinstallprompt", keepInstallOffer);
    addEventListener("appinstalled", dropInstallOffer);
    return () => {
      removeEventListener("beforeinstallprompt", keepInstallOffer);
      removeEventListener("appinstalled", dropInstallOffer);
    };
  }, []);
  return null;
}
