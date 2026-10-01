/**
 * Moves focus to the page's title (its h1, else <main>), the way RouteFocus does after a navigation: a panel that
 * closes (the first-login tour, the closed-engagement celebration) never drops focus to <body> (WCAG 2.4.3).
 */
export function focusPageTitle(): void {
  const main = document.getElementById("main");
  const target = main?.querySelector<HTMLElement>("h1") ?? main;
  if (!target) return;
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.classList.add("focus:outline-none"); // a heading is not a control: no ring
  target.focus({ preventScroll: true });
}
