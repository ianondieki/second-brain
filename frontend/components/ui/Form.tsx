"use client";

import type { FormHTMLAttributes } from "react";

import { useHydrated } from "@/lib/hooks/useHydrated";

import { Button, type ButtonProps } from "./Button";

/**
 * A form for credentials and codes. Two guards keep what people type out of URLs and logs when a submit happens
 * before the page's JavaScript has loaded (Slow 4G: about 2 s):
 * - method="post": a native submit sends the fields in the request body, never in a GET query string;
 * - its SubmitButton stays disabled until hydration, so neither a click nor Enter in a field submits natively
 *   (with the default button disabled, the browser skips implicit submission).
 * `data-hydrated` tells tests when the form is live.
 */
export function Form({ children, ...props }: Omit<FormHTMLAttributes<HTMLFormElement>, "method">) {
  const hydrated = useHydrated();
  return (
    <form method="post" noValidate data-hydrated={hydrated ? "true" : "false"} {...props}>
      {children}
    </form>
  );
}

/** The submit button of a Form: disabled until React has hydrated, then a normal (aria-disabled when busy) button. */
export function SubmitButton(props: Omit<ButtonProps, "type" | "disabled">) {
  const hydrated = useHydrated();
  return <Button type="submit" disabled={!hydrated} {...props} />;
}
