import type { Metadata } from "next";
import { RunsView } from "@/views/RunsView";

export const metadata: Metadata = { title: "Ejecuciones · Oficina HACK 30X" };

export default function Page() {
  return <RunsView />;
}
