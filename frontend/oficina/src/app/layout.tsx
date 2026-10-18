import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "HACK 30X · Oficina de tendencias",
  description:
    "Oficina virtual de HACK 30X: entra a cada puesto para usar DETECTAR, que detecta temas reales en crecimiento en América Latina con su evidencia.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#070d1c", colorScheme: "dark" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
