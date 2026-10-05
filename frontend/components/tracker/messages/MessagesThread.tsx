"use client";

import { Suspense, use, type ComponentProps } from "react";

import { preloadable } from "@/lib/preloadable";

// The Messages tab's code (REQ-ENG-11) loads only when the tab is open: the tracker's other tabs sit at the JS budget
// (docs/spec/07 item 5, 150 KB per route), and this shim is all they carry of it. Server-rendered whole (preloadable),
// so the thread arrives as HTML and nothing shifts while its chunk loads. Never import ./Thread statically
// (messages/thread-load.test.tsx fails if this module does).
const threadModule = preloadable(() => import("./Thread"));

/** Starts loading the thread's code (tests render it at once). */
export function preloadThread() {
  return threadModule();
}

function Loaded(props: ComponentProps<typeof import("./Thread").Thread>) {
  const { Thread } = use(threadModule());
  return <Thread {...props} />;
}

/** The thread, its report sheet and its composer, as one lazily loaded island. */
export function MessagesThread(props: ComponentProps<typeof import("./Thread").Thread>) {
  return (
    <Suspense fallback={null}>
      <Loaded {...props} />
    </Suspense>
  );
}
