// The browser's offer to install Wazo (`beforeinstallprompt`, Chromium browsers; P27 track F): kept by the shell's island
// when it fires, so the account menu can show "Install Wazo" and call its prompt(). Nothing on iOS, where the
// manifest (app/manifest.ts) and Share › Add to Home Screen are all there is.

interface InstallOffer extends Event {
  prompt(): Promise<unknown>;
}

let offer: InstallOffer | null = null;
const listeners = new Set<() => void>();

function changed() {
  for (const listener of listeners) listener();
}

/** `beforeinstallprompt`: keeps the event (and stops the browser's own mini-infobar) for the menu's entry. */
export function keepInstallOffer(event: Event): void {
  event.preventDefault();
  offer = event as InstallOffer;
  changed();
}

/** `appinstalled`, or the offer used: the entry goes. */
export function dropInstallOffer(): void {
  offer = null;
  changed();
}

export function installOffered(): boolean {
  return offer !== null;
}

export function subscribeInstall(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Shows the browser's install prompt (an offer can be used once). */
export async function install(): Promise<void> {
  const used = offer;
  dropInstallOffer();
  await used?.prompt().catch(() => {});
}
