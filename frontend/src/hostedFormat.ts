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

/** What the operator sells. Admin presets and the default renewal text both read this. */
export type HostedPackage = {
  id: string;
  name: string;
  minutes: number;
  validDays: number;
  price: number;
  hint: string;
  /** Days of AI memory included (the monthly card's perk). */
  memoryDays: number;
  /** The new-user first-month offer: an admin preset, shown to users as a tag on the full-price card. */
  firstTimeOnly?: boolean;
  /** First-month price advertised on the full-price card. */
  firstPrice?: number;
};

// Prices settled 2026-10-15: monthly card ¥129 (¥99 for a new user's first
// month, once), minute pack ¥99, 30 free minutes on sign-up.
export const HOSTED_PACKAGES: HostedPackage[] = [
  { id: "trial", name: "新人体验", minutes: 30, validDays: 30, price: 0, hint: "免费", memoryDays: 0 },
  {
    id: "monthly_first",
    name: "月卡·首月",
    minutes: 300,
    validDays: 30,
    price: 99,
    hint: "新用户首月，每人限一次",
    memoryDays: 30,
    firstTimeOnly: true,
  },
  {
    id: "monthly",
    name: "月卡",
    minutes: 300,
    validDays: 30,
    price: 129,
    hint: "推荐，适合每天练，含 AI 记忆",
    memoryDays: 30,
    firstPrice: 99,
  },
  { id: "pack", name: "分钟包", minutes: 200, validDays: 90, price: 99, hint: "适合偶尔练", memoryDays: 0 },
];

/** Packages a user can choose from (the first-month offer shows as a tag instead). */
export const USER_PACKAGES = HOSTED_PACKAGES.filter((pkg) => pkg.price > 0 && !pkg.firstTimeOnly);

export function packageNote(pkg: HostedPackage): string {
  return pkg.price > 0 ? `${pkg.name} ¥${pkg.price}` : pkg.name;
}

/** Suggested renewal text, built from the same price list. */
export function defaultRenewalText(): string {
  const lines = HOSTED_PACKAGES.filter((pkg) => !pkg.firstTimeOnly).map((pkg) =>
    pkg.price > 0
      ? `${pkg.name} ¥${pkg.price}：${pkg.minutes} 分钟，${pkg.validDays} 天内有效（${pkg.hint}）` +
        (pkg.firstPrice ? `，新用户首月只要 ¥${pkg.firstPrice}` : "")
      : `${pkg.name}：注册即送 ${pkg.minutes} 分钟（${pkg.validDays} 天内有效）`,
  );
  return [
    ...lines,
    "",
    "AI 记忆：外教会记住你的名字、水平和聊过的话题，月卡自带",
    "深度思考版 1 分钟按 1.5 分钟计；通义千问 1 分钟只扣 0.5 分钟",
    "扫码转账后，微信留言你的账号和套餐，当天到账",
  ].join("\n");
}
