"use client";

import { Info } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

/**
 * Explicación breve accesible: se abre con foco, puntero o clic, y se cierra con Escape.
 * El texto también está asociado con aria-describedby para lectores de pantalla.
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="infotip" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="infotip__btn"
        aria-label={`Qué significa: ${label}`}
        aria-describedby={id}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <Info size={14} aria-hidden="true" />
      </button>
      <span id={id} role="tooltip" className="infotip__bubble" data-open={open}>
        {children}
      </span>
    </span>
  );
}
