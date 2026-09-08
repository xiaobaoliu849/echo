import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { UseSettingsResult } from "../hooks/useSettings";
import SettingsPage from "../pages/SettingsPage";
import type { ErrorRuntimeContext } from "../types/ui";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: UseSettingsResult;
  errorRuntimeContext?: ErrorRuntimeContext;
};

export default function SettingsModal({ open, onClose, settings, errorRuntimeContext }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // Escape key dismisses the settings workspace
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Lock body scroll
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Auto focus
  useEffect(() => {
    if (!open || !dialogRef.current) return;
    dialogRef.current.focus();
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="vsSettingsModalShell"
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="vsSettingsModalStage"
        tabIndex={-1}
      >
        <SettingsPage settings={settings} errorRuntimeContext={errorRuntimeContext} onClose={onClose} />
      </div>
    </div>,
    document.body
  );
}
