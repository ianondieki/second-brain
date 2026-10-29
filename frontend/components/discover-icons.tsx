import { Icon, type IconProps } from "./ui/status-icons";

// Icons of Discover and "Recommended for you", drawn like components/ui/icons.tsx (20 px grid, 1.75 stroke, round
// joins, currentColor, decorative: the words next to them carry the meaning). A module of their own, so other screens
// add no bytes for them.

/** Discover: a compass. */
export function DiscoverIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="7.25" />
      <path d="m12.9 7.1-1.7 4.1-4.1 1.7 1.7-4.1Z" />
    </Icon>
  );
}

/** A trend rising: the mark in front of a self-explaining trend badge. */
export function TrendIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m2.75 14.25 4.5-4.5 3 3 6.5-6.5" />
      <path d="M12.5 6.25h4.25v4.25" />
    </Icon>
  );
}

/** New this week: a small spark. */
export function NewIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 2.75v3.5M10 13.75v3.5M2.75 10h3.5M13.75 10h3.5" />
      <path d="m5.2 5.2 1.6 1.6M13.2 13.2l1.6 1.6M5.2 14.8l1.6-1.6M13.2 6.8l1.6-1.6" />
    </Icon>
  );
}

/** Pursuit "Pursue": a filled circle with a check. */
export function PursueIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="8" fill="currentColor" stroke="none" />
      <path d="m6.5 10.25 2.4 2.4 4.6-5.1" stroke="var(--paper)" strokeWidth="2" />
    </Icon>
  );
}

/** Pursuit "Consider": a circle, half filled. */
export function ConsiderIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="7.25" />
      <path d="M10 2.75a7.25 7.25 0 0 1 0 14.5Z" fill="currentColor" />
    </Icon>
  );
}

/** Pursuit "Not now": a circle with a pause. */
export function NotNowIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="7.25" />
      <path d="M8.25 7v6M11.75 7v6" strokeWidth="2" />
    </Icon>
  );
}

/** A Why chip: a small filled diamond. */
export function WhyIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m10 5.5 4.5 4.5-4.5 4.5-4.5-4.5Z" fill="currentColor" stroke="none" />
    </Icon>
  );
}
