import type { Metadata } from "next";

import { LabView } from "@/views/crear/LabView";

export const metadata: Metadata = { title: "Laboratorio creativo · Oficina HACK 30X" };

export default function Page() {
  return <LabView />;
}
