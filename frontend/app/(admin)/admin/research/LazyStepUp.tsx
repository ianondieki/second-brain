"use client";

import { lazy, Suspense } from "react";

import type { StepUpProps } from "./StepUp";

const Form = lazy(() => import("./StepUp").then((module) => ({ default: module.StepUp })));

/**
 * The fresh-code form (StepUp), fetched only when the API asks for it: a console page then carries none of it until
 * then (the moderation case page was over the 150 KB budget with it; P25). It takes focus when it arrives, as before.
 */
export function LazyStepUp(props: StepUpProps) {
  return (
    <Suspense fallback={null}>
      <Form {...props} />
    </Suspense>
  );
}
