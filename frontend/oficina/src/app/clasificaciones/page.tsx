import type { Metadata } from "next";
import { ClassificationsView } from "@/views/ClassificationsView";

export const metadata: Metadata = { title: "Clasificaciones · Oficina HACK 30X" };

export default function Page() {
  return <ClassificationsView />;
}
