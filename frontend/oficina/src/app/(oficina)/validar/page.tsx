import type { Metadata } from "next";

import { ValidationView } from "@/views/StationView";

export const metadata: Metadata = { title: "Sala de validación · HACK 30X" };

export default function Page() {
  return <ValidationView />;
}
