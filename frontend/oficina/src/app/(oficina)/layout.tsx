import { Suspense, type ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";

/** Vistas de trabajo de la oficina: comparten la navegación lateral. La landing (/) no. */
export default function OficinaLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={null}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
