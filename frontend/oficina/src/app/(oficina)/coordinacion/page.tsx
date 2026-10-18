import type { Metadata } from "next";

import { CoordinationView } from "@/views/CoordinationView";

export const metadata: Metadata = { title: "Centro de agentes · HACK 30X" };

export default function Page() {
  return <CoordinationView />;
}
