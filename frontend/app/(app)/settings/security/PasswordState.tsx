"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

interface PasswordState {
  /** The account has a password: credential changes on this page must confirm it. */
  hasPassword: boolean;
  /** Called when a password is saved here, or when the API answers current_password_required. Never reverts. */
  markPasswordSet: () => void;
  /** Two-step setup (steps 1-3) or new recovery codes are on screen: the Password section steps aside until they end. */
  enrolling: boolean;
  setEnrolling: (enrolling: boolean) => void;
}

const Context = createContext<PasswordState | null>(null);

/**
 * What the Password section and two-step setup share on the security page. "Has a password" starts from
 * GET /api/auth/me (user.password_set) and only ever turns on, so a field the API asked for cannot disappear while
 * someone types into it, and a password saved in the Password section is asked for by two-step setup straight away.
 * "Enrolling" hides the Password section while the setup steps are shown, so the page holds one task at a time.
 */
export function PasswordStateProvider({ initial, children }: { initial: boolean; children: ReactNode }) {
  const [hasPassword, setHasPassword] = useState(initial);
  const [enrolling, setEnrolling] = useState(false);
  return (
    <Context.Provider value={{ hasPassword, markPasswordSet: () => setHasPassword(true), enrolling, setEnrolling }}>
      {children}
    </Context.Provider>
  );
}

export function usePasswordState(): PasswordState {
  const state = useContext(Context);
  if (!state) throw new Error("usePasswordState needs a PasswordStateProvider");
  return state;
}
