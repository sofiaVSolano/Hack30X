import type { Metadata } from "next";
import { TopicsView } from "@/views/TopicsView";

export const metadata: Metadata = { title: "Temas · Oficina HACK 30X" };

export default function Page() {
  return <TopicsView />;
}
