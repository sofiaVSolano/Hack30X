import type { Metadata } from "next";

import { StationView } from "@/views/StationView";

export const metadata: Metadata = { title: "Puesto de agente · HACK 30X" };

export default async function Page({ params }: { params: Promise<{ agente: string }> }) {
  const { agente } = await params;
  return <StationView agentId={decodeURIComponent(agente)} />;
}
