"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { LazyStepUp as StepUp } from "./LazyStepUp";

/**
 * The step-up in place of a whole research screen: once the code is accepted the page is fetched again, and when this
 * form leaves the page focus moves to the page's heading, so it is not lost.
 */
export function PageStepUp() {
  const router = useRouter();
  const confirmed = useRef(false);
  useEffect(
    () => () => {
      // Runs after the refreshed page has replaced this form.
      if (confirmed.current) document.querySelector<HTMLElement>("main h1")?.focus();
    },
    [],
  );
  return (
    <StepUp
      onConfirmed={() => {
        confirmed.current = true;
        router.refresh();
      }}
    />
  );
}
