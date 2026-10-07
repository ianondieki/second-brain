import type { ReactNode, SVGProps } from "react";

// Icons from Lucide v0.544.0 (https://lucide.dev, lucide-static), ISC licence: copyright Lucide Contributors 2025,
// portions copyright Cole Bemis 2013-2023 as part of Feather (MIT). The full licence is in
// frontend/THIRD_PARTY_NOTICES.md. Vendored by hand, only the icons the product draws (P23-2, D-65): the paths are
// Lucide's own on its 24-unit grid; the stroke is set at 1.75 so they sit with the product's own icons
// (components/ui/status-icons.tsx). No package, no CDN, no icon font. Decorative: the words beside them carry the meaning.

export type LucideProps = SVGProps<SVGSVGElement>;

function Lucide({ children, ...props }: LucideProps & { children: ReactNode }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
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

export function HouseIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" />
      <path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </Lucide>
  );
}

export function BadgeCheckIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z" />
      <path d="m9 12 2 2 4-4" />
    </Lucide>
  );
}

export function RouteIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <circle cx="6" cy="19" r="3" />
      <path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15" />
      <circle cx="18" cy="5" r="3" />
    </Lucide>
  );
}

export function InboxIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    </Lucide>
  );
}

export function FileLockIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v1" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
      <rect width="8" height="5" x="2" y="13" rx="1" />
      <path d="M8 13v-2a2 2 0 1 0-4 0v2" />
    </Lucide>
  );
}

export function FileCheckIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
      <path d="m3 15 2 2 4-4" />
    </Lucide>
  );
}

export function ShieldCheckIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
      <path d="m9 12 2 2 4-4" />
    </Lucide>
  );
}

export function ArrowLeftIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="m12 19-7-7 7-7" />
      <path d="M19 12H5" />
    </Lucide>
  );
}

export function ArrowRightIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </Lucide>
  );
}

export function PauseIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <rect x="14" y="3" width="5" height="18" rx="1" />
      <rect x="5" y="3" width="5" height="18" rx="1" />
    </Lucide>
  );
}

export function PlayIcon(props: LucideProps) {
  return (
    <Lucide {...props}>
      <path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" />
    </Lucide>
  );
}
