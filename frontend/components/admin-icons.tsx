import { Icon, type IconProps } from "./ui/status-icons";

// Icons of the staff console, drawn like components/ui/icons.tsx (20 px grid, 1.75 stroke, round joins, currentColor,
// decorative: the words next to them carry the meaning). A module of their own, so the portals add no bytes for them.

/** Research: a page of notes under a magnifying glass. */
export function ResearchIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M11.25 16.75h-6.5V3.25h8.5v4" />
      <path d="M7.25 7h3.5M7.25 10h2" />
      <circle cx="13.75" cy="12.25" r="2.75" />
      <path d="m15.75 14.25 2 2" />
    </Icon>
  );
}

/** Moderation: a shield with a tick (content checked before it goes out). */
export function ModerationIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 2.75 3.75 5.25v4.5c0 3.6 2.6 6.4 6.25 7.5 3.65-1.1 6.25-3.9 6.25-7.5v-4.5Z" />
      <path d="m7.25 10 2 2 3.5-3.75" />
    </Icon>
  );
}

/** Claims: a building with a small badge (an organisation asking to be verified). */
export function ClaimsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.25 16.75h9.5M4.75 16.75V5.25l5-2.5 1.5.75v13.25" />
      <path d="M7.25 7.75h.01M7.25 10.75h.01M7.25 13.75h.01" strokeWidth="2.25" />
      <circle cx="14.75" cy="12.75" r="2.75" />
      <path d="m13.75 15.25-.5 2 1.5-.75 1.5.75-.5-2" />
    </Icon>
  );
}

/** Quiz: a card with five lines and a tick (Today's five, approved before anyone plays it). */
export function QuizIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.25" y="3.25" width="13.5" height="13.5" rx="2.5" />
      <path d="M6.5 7.25h4.25M6.5 10h3M6.5 12.75h2" />
      <path d="m11.75 12 1.5 1.5 2.5-2.75" />
    </Icon>
  );
}
