/**
 * Closes the open overflow menus (Overflow.tsx, `details[data-overflow]`): on Escape (focus goes back to the menu's
 * button), on a press outside the menu, and on a press of one of its items (focus goes to the menu's button, so a
 * dialog the item opens gives focus back there). A page with menus listens with it on the document for click and
 * keydown.
 */
export function closeOverflows(event: Event) {
  const target = event.target as Element;
  const escape = (event as KeyboardEvent).key === "Escape";
  for (const menu of document.querySelectorAll<HTMLDetailsElement>("details[data-overflow][open]")) {
    if (event.type === "keydown" ? !escape : menu.contains(target) && !target.closest("button")) continue;
    if (menu.contains(escape ? document.activeElement : target)) menu.querySelector("summary")?.focus();
    menu.open = false;
  }
}
