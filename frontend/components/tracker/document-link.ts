import { standaloneLinkClass } from "@/components/ui/Button";

/**
 * A document link's classes: the one shown reads as the current item (ink, bold, no underline), the others as
 * standalone links. Chosen whole, not joined: `cn` only concatenates, so an added `text-ink` would not beat the link's
 * own `text-accent`.
 */
export function documentLinkClass(current: boolean): string {
  return current ? "inline-flex min-h-11 items-center font-semibold text-ink no-underline" : standaloneLinkClass;
}
