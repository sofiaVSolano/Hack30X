import type { Metadata } from "next";
import { AgentsView } from "@/views/AgentsView";

export const metadata: Metadata = { title: "Agentes · Oficina HACK 30X" };

export default function Page() {
  return <AgentsView />;
}
