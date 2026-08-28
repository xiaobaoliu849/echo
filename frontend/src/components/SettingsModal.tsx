import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { UseSettingsResult } from "../hooks/useSettings";
import SettingsPage from "../pages/SettingsPage";
import type { ErrorRuntimeContext } from "../types/ui";
import { useI18n } from "../i18n";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: UseSettingsResult;
  errorRuntimeContext?: ErrorRuntimeContext;
};

export default function SettingsModal({ open, onClose, settings, errorRuntimeContext }: Props) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);

  // The minimize/maximize controls only affect the settings panel itself:
  // minimize hides the panel (the app stays open) and maximize expands it to
  // fill the app window. They never touch the native OS window.
  const [maximized, setMaximized] = useState(false);

  const handleMinimize = useCallback(() => {
    onClose();
  }, [onClose]);

  const handleToggleMaximize = useCallback(() => {
    setMaximized((prev) => !prev);
    // Drop any drag offset so the panel returns to its centered position.
    const ds = dragState.current;
    ds.offsetX = 0;
    ds.offsetY = 0;
    if (dialogRef.current) {
      dialogRef.current.style.transform = "translate(0, 0)";
    }
  }, []);

  // Drag state stored in a ref — never triggers React re-render
  const dragState = useRef({
    isDragging: false,
    startX: 0,
    startY: 0,
    offsetX: 0,
    offsetY: 0,
  });

  // Reset position and maximized state when modal opens
  useEffect(() => {
    if (open && dialogRef.current) {
      dragState.current = { isDragging: false, startX: 0, startY: 0, offsetX: 0, offsetY: 0 };
      dialogRef.current.style.transform = "translate(0, 0)";
      setMaximized(false);
    }
  }, [open]);

  // High-performance drag using direct DOM manipulation
  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    // A maximized panel fills the window and cannot be dragged
    if (maximized) return;
    // Only drag from the header bar, skip clicks on buttons
    const target = e.target as HTMLElement;
    if (target.closest("button")) return;

    const ds = dragState.current;
    ds.isDragging = true;
    ds.startX = e.clientX - ds.offsetX;
    ds.startY = e.clientY - ds.offsetY;

    // Capture pointer for smooth drag even outside the element
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    e.preventDefault();
  }, [maximized]);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const ds = dragState.current;
    if (!ds.isDragging || !dialogRef.current) return;

    let newX = e.clientX - ds.startX;
    let newY = e.clientY - ds.startY;

    // Clamp so the modal stays mostly on-screen
    // Keep at least 200px visible horizontally and 60px vertically
    const rect = dialogRef.current.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // The modal is initially centered, so its "home" position is:
    // centerX = (vw - w) / 2, centerY = (vh - h) / 2
    // With offset (newX, newY), the actual left = centerX + newX
    const centerX = (vw - w) / 2;
    const centerY = (vh - h) / 2;
    const minVisible = 200; // px that must remain on screen horizontally
    const minVisibleY = 60;  // px that must remain on screen vertically

    // Left edge: left = centerX + newX >= -(w - minVisible)
    // Right edge: left = centerX + newX <= vw - minVisible
    const minX = -(w - minVisible) - centerX;
    const maxX = (vw - minVisible) - centerX;
    newX = Math.max(minX, Math.min(maxX, newX));

    // Top edge: top >= -(h - minVisibleY)
    // Bottom edge: top <= vh - minVisibleY
    const minY = -(h - minVisibleY) - centerY;
    const maxY = (vh - minVisibleY) - centerY;
    newY = Math.max(minY, Math.min(maxY, newY));

    ds.offsetX = newX;
    ds.offsetY = newY;

    // Direct DOM write — zero React re-renders
    dialogRef.current.style.transform = `translate(${newX}px, ${newY}px)`;
  }, []);

  const onPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    dragState.current.isDragging = false;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
  }, []);

  // Escape key
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
      className={maximized ? "vsSettingsModalShell maximized" : "vsSettingsModalShell"}
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className={maximized ? "vsSettingsModalStage maximized" : "vsSettingsModalStage"}
        tabIndex={-1}
      >
        <div
          ref={headerRef}
          className="vsSettingsModalHeader"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          style={{ cursor: "grab" }}
        >
          <div className="vsSettingsModalHeaderTitleRow">
            <span className="vsSettingsModalHeaderIcon">⚙️</span>
            <h2>{t("偏好设置", "Preferences")}</h2>
          </div>
          <div className="vsSettingsModalWindowControls">
            <button
              type="button"
              className="vsWindowControlBtn minimize"
              onClick={handleMinimize}
              title={t("最小化", "Minimize")}
              aria-label={t("最小化", "Minimize")}
            >
              —
            </button>
            <button
              type="button"
              className="vsWindowControlBtn maximize"
              onClick={handleToggleMaximize}
              title={maximized ? t("还原", "Restore") : t("最大化", "Maximize")}
              aria-label={maximized ? t("还原", "Restore") : t("最大化", "Maximize")}
            >
              {maximized ? "❐" : "▢"}
            </button>
            <button
              type="button"
              className="vsWindowControlBtn close"
              onClick={onClose}
              title={t("关闭", "Close")}
              aria-label={t("关闭", "Close")}
            >
              ✕
            </button>
          </div>
        </div>
        <SettingsPage settings={settings} errorRuntimeContext={errorRuntimeContext} onClose={onClose} />
      </div>
    </div>,
    document.body
  );
}
