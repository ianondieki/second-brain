// After a change that refreshes the tracker (a declaration recorded, or refused for good), focus moves to the
// declaration's line once the refreshed line is on the page: its words change (or it goes, on an ended engagement,
// when the actions' heading takes focus). Watched with a MutationObserver over the turn card, never on a timer; a
// change elsewhere in the card (the clock's figures) is not the line's and is ignored. Loaded with the sheet.

/** The declaration line's id (components/team/TeamPanel.tsx DeclarationLine). */
export const LINE_ID = "prior-knowledge";

/** Arms the move; returns the observer (disconnected once it moved focus), or null when there is no line to watch. */
export function focusLineWhenRefreshed(doc: Document = document): MutationObserver | null {
  const line = doc.getElementById(LINE_ID);
  if (!line) return null;
  const before = line.textContent;
  const root = line.closest("[data-turn-card]") ?? doc.body;
  const observer = new MutationObserver(() => {
    const now = doc.getElementById(LINE_ID);
    if (now && now.textContent === before) return;
    observer.disconnect();
    (now ?? doc.getElementById("actions-heading"))?.focus();
  });
  observer.observe(root, { subtree: true, childList: true, characterData: true });
  return observer;
}
