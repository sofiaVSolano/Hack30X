"use client";

import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

import styles from "./Dialog.module.css";

/**
 * Panel lateral o modal sobre <dialog> nativo: `showModal()` atrapa el foco, Escape cierra y
 * el foco vuelve al elemento que lo abrió.
 */
export function Dialog({
  open,
  onClose,
  title,
  subtitle,
  variant = "drawer",
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  variant?: "drawer" | "modal";
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const handleClose = () => {
      const target = opener.current;
      if (target instanceof HTMLElement && target.isConnected) target.focus();
      onClose();
    };
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [onClose]);

  return (
    <dialog
      ref={ref}
      className={`${styles.dialog} ${variant === "drawer" ? styles.drawer : styles.modal}`}
      aria-labelledby={titleId}
      onClick={(event) => {
        // Clic en el fondo (fuera del contenido) cierra.
        if (event.target === ref.current) ref.current?.close();
      }}
    >
      {open ? (
        <div className={styles.inner}>
          <header className={styles.head}>
            <div>
              <h2 id={titleId} className={styles.title}>
                {title}
              </h2>
              {subtitle ? <div className={styles.subtitle}>{subtitle}</div> : null}
            </div>
            <button type="button" className="btn btn--ghost btn--icon" onClick={() => ref.current?.close()} aria-label="Cerrar">
              <X size={18} aria-hidden="true" />
            </button>
          </header>
          <div className={styles.body}>{children}</div>
        </div>
      ) : null}
    </dialog>
  );
}
