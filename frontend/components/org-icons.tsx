import type { ReactNode, SVGProps } from "react";

// Icons of the organisation screens, drawn like components/ui/icons.tsx (20 px grid, 1.75 stroke, round joins,
// currentColor, decorative: the words next to them carry the meaning). A module of their own, so the organisation
// side adds no bytes to the shared icon set.

type IconProps = SVGProps<SVGSVGElement>;

function Svg({ children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

/** Inbox: a tray with a dip where a proposal lands. */
export function InboxIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2.75 11.25 5 4.25h10l2.25 7" />
      <path d="M2.75 11.25v4.5h14.5v-4.5h-4.25l-1.25 2h-3.5l-1.25-2Z" />
    </Svg>
  );
}

/** The full proposal: a closed padlock (behind the NDA), open once it may be read. */
export function ConfidentialIcon({ open = false, ...props }: IconProps & { open?: boolean }) {
  return (
    <Svg {...props}>
      <rect x="4.25" y="8.75" width="11.5" height="8.5" rx="1.5" />
      <path d={open ? "M7 8.75V6a3 3 0 0 1 5.8-1.1" : "M7 8.75V6a3 3 0 0 1 6 0v2.75"} />
      <path d="M10 12.25v1.75" />
    </Svg>
  );
}
