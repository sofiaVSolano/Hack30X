import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import { Suspense, type ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";

export const metadata: Metadata = {
  title: "Oficina de agentes · HACK 30X",
  description: "Actividad verificable de los agentes de DETECTAR: ejecuciones, programador, temas, métricas y clasificaciones.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#090d13", colorScheme: "dark" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>
        <Suspense fallback={null}>
          <AppShell>{children}</AppShell>
        </Suspense>
      </body>
    </html>
  );
}
