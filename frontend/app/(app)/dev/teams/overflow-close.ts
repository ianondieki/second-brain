/**
 * Closes the open overflow menus (Overflow.tsx, `details[data-overflow]`): on Escape (focus goes back to the menu's
 * button), on a press outside the menu, and on a press of one of its items (focus goes to the menu's button, so a
 * dialog the item opens gives focus back there). A page with menus listens with it on the document for click and
 * keydown.
 */
export function closeOverflows(event: Event) {
  for (const menu of document.querySelectorAll<HTMLDetailsElement>("details[data-overflow][open]")) {
    const summary = menu.querySelector("summary");
    if (event.type === "keydown") {
      if ((event as KeyboardEvent).key !== "Escape") continue;
      if (menu.contains(document.activeElement)) summary?.focus();
    } else {
      const target = event.target as Element;
      if (menu.contains(target)) {
        if (!target.closest("button")) continue;
        summary?.focus();
      }
    }
    menu.open = false;
  }
}
