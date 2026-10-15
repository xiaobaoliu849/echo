import { useState, type FormEvent } from "react";
import type { HostedDailyUsage } from "./api";
import { HOSTED_MODEL_LABELS } from "./hosted";
import { formatErrorMessage } from "./utils/errorFormatting";

// Formatting and form helpers shared by the hosted account and admin pages.

export function minutes(seconds: number): string {
  // Round down: a balance must never look bigger than it is.
  const value = seconds / 60;
  if (Math.abs(value) >= 100 || Number.isInteger(value)) {
    return String(Math.trunc(value));
  }
  return (Math.trunc(value * 10) / 10).toFixed(1);
}

export function formatTime(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) {
    return "—";
  }
  const date = new Date(epochSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Calendar date, e.g. 2027-01-13; for expiry dates a year away. */
export function formatDate(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  return `${m}:${String(seconds % 60).padStart(2, "0")}`;
}

export function modelLabel(model: string): string {
  return HOSTED_MODEL_LABELS[model] || model || "—";
}

/** One entry per calendar day in the period, so quiet days show as gaps. */
export function fillDays(daily: HostedDailyUsage[], days: number): HostedDailyUsage[] {
  const byDay = new Map(daily.map((row) => [row.day, row]));
  const out: HostedDailyUsage[] = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i -= 1) {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    out.push(byDay.get(key) || { day: key, wall_seconds: 0, billed_seconds: 0, users: 0 });
  }
  return out;
}

export function useSubmit(action: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(formatErrorMessage(err, "操作失败"));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, submit };
}
