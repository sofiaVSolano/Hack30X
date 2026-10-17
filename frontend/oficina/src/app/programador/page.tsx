import type { Metadata } from "next";
import { SchedulerView } from "@/views/SchedulerView";

export const metadata: Metadata = { title: "Programador · Oficina HACK 30X" };

export default function Page() {
  return <SchedulerView />;
}
