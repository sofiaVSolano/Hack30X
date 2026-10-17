import type { Metadata } from "next";
import { MetricsView } from "@/views/MetricsView";

export const metadata: Metadata = { title: "Métricas · Oficina HACK 30X" };

export default function Page() {
  return <MetricsView />;
}
