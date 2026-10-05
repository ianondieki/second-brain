import { Icon, type IconProps } from "@/components/ui/status-icons";

/** A file: a sheet with a folded corner and two lines of text. */
export function FileIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M11.5 2.75H6a1.5 1.5 0 0 0-1.5 1.5v11.5a1.5 1.5 0 0 0 1.5 1.5h8a1.5 1.5 0 0 0 1.5-1.5v-9z" />
      <path d="M11.5 2.75v4h4" />
      <path d="M7.5 11h5M7.5 13.75h3.5" />
    </Icon>
  );
}

/** A paper clip, for attaching files. */
export function ClipIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m15.5 9.25-5.6 5.6a3.25 3.25 0 0 1-4.6-4.6l6-6a2.15 2.15 0 0 1 3.05 3.05l-6 6a1.05 1.05 0 0 1-1.5-1.5l5.6-5.6" />
    </Icon>
  );
}
