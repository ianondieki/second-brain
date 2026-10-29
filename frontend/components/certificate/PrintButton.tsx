"use client";

import { Button } from "@/components/ui/Button";

/** Prints the page: the print stylesheet (app/globals.css) keeps only the certificate sheet. */
export function PrintButton({ label }: { label: string }) {
  return (
    <Button variant="secondary" onClick={() => window.print()} data-no-print="">
      {label}
    </Button>
  );
}
