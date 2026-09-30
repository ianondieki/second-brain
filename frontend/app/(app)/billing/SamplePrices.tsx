import { InfoIcon } from "@/components/ui/status-icons";

/** The D-44 label beside prices while plans.yaml holds placeholders: an icon and words, never colour alone. */
export function SamplePrices({ label }: { label: string }) {
  return (
    <p
      data-sample-prices=""
      className="inline-flex items-center gap-1.5 rounded-control border border-line px-2.5 py-1 text-sm font-medium text-ink-soft"
    >
      <InfoIcon className="size-4 shrink-0 text-jacaranda" />
      {label}
    </p>
  );
}
