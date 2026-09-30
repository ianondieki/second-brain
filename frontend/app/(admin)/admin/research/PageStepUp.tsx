"use client";

import { useRouter } from "next/navigation";

import { StepUp } from "./StepUp";

/** The step-up in place of a whole research screen: once the code is accepted, the page is fetched again. */
export function PageStepUp() {
  const router = useRouter();
  return <StepUp onConfirmed={() => router.refresh()} />;
}
