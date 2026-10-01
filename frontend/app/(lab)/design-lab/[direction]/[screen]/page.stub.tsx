import { notFound } from "next/navigation";

/** Production stand-in for page.lab.tsx: the design lab is development only, so this address is not found. */
export default function DesignLabStub() {
  notFound();
}
