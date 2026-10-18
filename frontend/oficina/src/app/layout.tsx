import "@fontsource-variable/archivo/wdth.css";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "HACK 30X · DETECTAR",
  description: "Actividad verificable de los agentes de DETECTAR: ejecuciones, programador, temas, métricas y clasificaciones.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#F1ECDF", colorScheme: "light" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>
        {children}
      </body>
    </html>
  );
}
