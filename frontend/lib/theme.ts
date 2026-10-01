// Dark mode (D-52): the system preference by default, a choice remembered per browser. The choice is written on <html
// data-theme="light|dark"> before the first paint by THEME_INIT_SCRIPT (app/layout.tsx), so a dark page never flashes
// light; with no choice the attribute is absent and app/globals.css follows prefers-color-scheme.

export const THEME_STORAGE_KEY = "wazo-theme";
export const THEMES = ["system", "light", "dark"] as const;
export type ThemeChoice = (typeof THEMES)[number];

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

/** Reads the remembered choice; "system" when none, or when storage is unavailable. */
export function readTheme(storage: Pick<Storage, "getItem"> | null | undefined): ThemeChoice {
  try {
    const value = storage?.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(value) ? value : "system";
  } catch {
    return "system";
  }
}

/** Writes the choice to the document (and storage): the attribute for a choice, none for "system". */
export function applyTheme(choice: ThemeChoice, root: HTMLElement, storage: Pick<Storage, "setItem" | "removeItem"> | null | undefined) {
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try {
    if (choice === "system") storage?.removeItem(THEME_STORAGE_KEY);
    else storage?.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // A private window or blocked storage: the page still follows the choice until it is reloaded.
  }
}

/** Inline, before paint, no dependencies: the same logic as readTheme + applyTheme for the document only. */
export const THEME_INIT_SCRIPT =
  `(function(){try{var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});` +
  `if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t);}catch(e){}})();`;
