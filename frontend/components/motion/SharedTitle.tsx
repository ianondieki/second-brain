import { ViewTransition, type ReactNode } from "react";

// The App Router's React has <ViewTransition>; a React without it (the test runner's stable release) renders the
// content as it is.
const Transition: typeof ViewTransition | undefined = ViewTransition;

/** The shared name of a thing's title, the same on its card and on its page ("idea", the idea's id). */
export function titleName(kind: "idea" | "engagement" | "problem", id: string): string {
  return `title-${kind}-${id.replace(/[^\w-]/g, "")}`;
}

/**
 * A card's title that morphs into the detail page's h1 when the card is opened (D-67, P25): both carry the same name
 * (titleName). Only the pair moves (`share`); nothing else animates for it (`default="none"`). Where the next page
 * arrives after a loading state, or under reduced motion, there is no morph, only the page's cross-fade.
 */
export function SharedTitle({ kind, id, children }: { kind: "idea" | "engagement" | "problem"; id: string; children: ReactNode }) {
  if (!Transition) return <>{children}</>;
  return (
    <Transition name={titleName(kind, id)} share="title-morph" default="none">
      {children}
    </Transition>
  );
}
