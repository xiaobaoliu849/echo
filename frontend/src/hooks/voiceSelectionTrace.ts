/**
 * Ring buffer of realtime-selection transitions, shipped to the backend on
 * connect as the ``client_trace`` query parameter so it lands in backend.log.
 *
 * Why this exists: the backend log showed a call opening with
 * provider=DashScope right after the user picked AgentPlatform in the UI, yet
 * every isolated test of the hooks and of the popover's real click handlers
 * commits AgentPlatform correctly. The missing information is the order of
 * state transitions in the live app, which no test can reconstruct.
 */

const MAX_EVENTS = 14;

type TraceEvent = { seq: number; kind: string; detail: string };

let seq = 0;
const events: TraceEvent[] = [];

export function traceSelection(kind: string, detail: string): void {
  seq += 1;
  events.push({ seq, kind, detail });
  if (events.length > MAX_EVENTS) {
    events.splice(0, events.length - MAX_EVENTS);
  }
}

/** Compact single-line form: ``3:commit=AgentPlatform/gemini-...|4:reset=...`` */
export function serializeSelectionTrace(): string {
  return events.map((e) => `${e.seq}:${e.kind}=${e.detail}`).join("|");
}

export function resetSelectionTrace(): void {
  events.length = 0;
  seq = 0;
}
