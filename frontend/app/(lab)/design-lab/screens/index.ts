export const SCREENS = [
  { key: "landing", label: "Landing" },
  { key: "home", label: "Developer Home" },
  { key: "certificate", label: "Certificate" },
  { key: "tracker", label: "Tracker" },
  { key: "proposal", label: "NDA + full proposal" },
  { key: "checkout", label: "M-Pesa checkout" },
  { key: "email", label: "Email" },
  { key: "tokens", label: "Tokens" },
] as const;
export type ScreenKey = (typeof SCREENS)[number]["key"];

export function isScreen(value: string): value is ScreenKey {
  return SCREENS.some((s) => s.key === value);
}
