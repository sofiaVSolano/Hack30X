import { Suspense, type ReactNode } from "react";

import { OfficeWorld } from "@/components/office/OfficeWorld";

/**
 * La oficina persistente: el escenario isométrico se mantiene montado entre rutas y cada vista
 * de trabajo (`/tendencias`, `/temas`…) se abre como la pantalla del computador de su puesto.
 */
export default function OficinaLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={null}>
      <OfficeWorld>{children}</OfficeWorld>
    </Suspense>
  );
}
