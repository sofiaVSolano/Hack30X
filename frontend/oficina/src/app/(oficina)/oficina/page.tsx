import type { Metadata } from "next";

import { OfficeView } from "@/views/OfficeView";

export const metadata: Metadata = { title: "Oficina de agentes · HACK 30X" };

export default function Page() {
  return <OfficeView />;
}
