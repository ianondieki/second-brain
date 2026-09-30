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
