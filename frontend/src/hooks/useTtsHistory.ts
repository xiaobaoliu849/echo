import { useCallback, useEffect, useState } from "react";
import { buildSpeakUrl } from "../api";
import type { TtsEngine } from "../api";

const STORAGE_KEY = "vs_tts_history";
const MAX_ENTRIES = 50;

export type TtsHistoryEntry = {
  id: string;
  text: string;
  mode: "text" | "dialogue" | "pdf";
  engine: TtsEngine;
  engineB?: TtsEngine;
  model?: string;
  modelB?: string;
  voice: string;
  voiceB?: string;
  rate: string;
  createdAt: number;
};

function readStorage(): TtsHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidEntry);
  } catch {
    return [];
  }
}

function writeStorage(entries: TtsHistoryEntry[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // localStorage may be unavailable (private mode / quota); history is best-effort.
  }
}

function isValidEntry(value: unknown): value is TtsHistoryEntry {
  if (!value || typeof value !== "object") return false;
  const e = value as Record<string, unknown>;
  return (
    typeof e.id === "string" &&
    typeof e.text === "string" &&
    (e.mode === "text" || e.mode === "dialogue" || e.mode === "pdf") &&
    typeof e.engine === "string" &&
    typeof e.voice === "string" &&
    typeof e.rate === "string" &&
    typeof e.createdAt === "number"
  );
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export type UseTtsHistoryResult = {
  history: TtsHistoryEntry[];
  addEntry: (entry: Omit<TtsHistoryEntry, "id" | "createdAt">) => void;
  removeEntry: (id: string) => void;
  clearHistory: () => void;
  buildReplayUrl: (entry: TtsHistoryEntry) => string;
};

export default function useTtsHistory(): UseTtsHistoryResult {
  const [history, setHistory] = useState<TtsHistoryEntry[]>([]);

  useEffect(() => {
    setHistory(readStorage());
  }, []);

  const addEntry = useCallback((entry: Omit<TtsHistoryEntry, "id" | "createdAt">) => {
    setHistory((prev) => {
      const next = [{ ...entry, id: makeId(), createdAt: Date.now() }, ...prev].slice(0, MAX_ENTRIES);
      writeStorage(next);
      return next;
    });
  }, []);

  const removeEntry = useCallback((id: string) => {
    setHistory((prev) => {
      const next = prev.filter((e) => e.id !== id);
      writeStorage(next);
      return next;
    });
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    writeStorage([]);
  }, []);

  const buildReplayUrl = useCallback((entry: TtsHistoryEntry) => {
    return buildSpeakUrl({
      text: entry.text,
      voice: entry.voice || undefined,
      voiceB: entry.voiceB || undefined,
      rate: entry.rate || undefined,
      engine: entry.engine,
      engineB: entry.engineB || undefined,
      model: entry.model || undefined,
      modelB: entry.modelB || undefined,
    });
  }, []);

  return { history, addEntry, removeEntry, clearHistory, buildReplayUrl };
}
