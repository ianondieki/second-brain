"use client";

import { createContext, type ReactNode } from "react";

/** What the account menu offers on the screens inside an AccountMenuScope (everything, outside one). */
export const MenuOptions = createContext<{ billing: boolean }>({ billing: true });

/**
 * Tells the account menu of the screens inside it what the account has: a staff-only account (no developer or
 * organisation side of its own) has no plan, so its menu leaves out Plan & billing (P15-F MINOR 7). Used by the staff
 * console's shell; every other screen keeps the full menu. Its own module, so the console's reference to it does not
 * make the account menu itself a separately loaded chunk on every signed-in route.
 */
export function AccountMenuScope({ billing, children }: { billing: boolean; children: ReactNode }) {
  return <MenuOptions value={{ billing }}>{children}</MenuOptions>;
}
