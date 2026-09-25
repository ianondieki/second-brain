"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

interface PasswordState {
  /** The account has a password: credential changes on this page must confirm it. */
  hasPassword: boolean;
  /** Called when a password is saved here, or when the API answers current_password_required. Never reverts. */
  markPasswordSet: () => void;
}

const Context = createContext<PasswordState | null>(null);

/**
 * One "has a password" flag for the whole security page. It starts from GET /api/auth/me (user.password_set) and
 * only ever turns on, so a field the API asked for cannot disappear while someone types into it, and a password
 * saved in the Password section is asked for by two-step setup straight away.
 */
export function PasswordStateProvider({ initial, children }: { initial: boolean; children: ReactNode }) {
  const [hasPassword, setHasPassword] = useState(initial);
  return (
    <Context.Provider value={{ hasPassword, markPasswordSet: () => setHasPassword(true) }}>{children}</Context.Provider>
  );
}

export function usePasswordState(): PasswordState {
  const state = useContext(Context);
  if (!state) throw new Error("usePasswordState needs a PasswordStateProvider");
  return state;
}
