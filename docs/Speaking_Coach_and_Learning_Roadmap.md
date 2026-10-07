# Speaking Coach & Realtime Language-Learning Roadmap

> 2026-10-07. Direction: evolve Echo's realtime voice calls into a **conversation-learning app**
> (talk with an AI partner → get corrections → save phrases → spaced review).
> Inputs: a read-only repo review by Codex (GPT, `codex exec -s read-only`) + Claude's own review.
> Continues P2 of `VOICE_EXPERIENCE_NEXT_PHASES.md` ("雅思口语助教 / 即时语法纠错").

## Phase 0 — shipped: Speaking Coach MVP

Per-turn, non-blocking language feedback for **every realtime provider**.

| Piece | Where |
|---|---|
| Review service (prompt, JSON parsing/validation, tolerant provider resolution: DashScope → DeepSeek → Google → …, falls back to `qwen-flash` when no default chat model) | `backend/services/speaking_coach.py` |
| SQLite table `coach_feedback` in `voice_spirit.db` | `CoachRepository` in the same file |
| Hook: client command `coach_config` (separate from `config`, which would disable memory when sent without a memory payload); `_finalize_realtime_turn` schedules a bounded background review (≤2 in flight per connection, state on `websocket.state`) and emits `coach_feedback` | `backend/services/realtime_voice_service.py` |
| REST: `GET /api/coach/feedback`, `GET /api/coach/summary`, `DELETE /api/coach/feedback/{id}` | `backend/routers/coach.py` |
| Toggle + practice language + level (入门/中级/高级/雅思), persisted in localStorage `vs_speaking_coach` | `VoiceCallSettingsPopover.tsx` → 音色设定 tab, `utils/speakingCoach.ts` |
| Feedback card under each user bubble (correction, issues, useful phrases, tip, "misheard — remove") | `components/chat/CoachFeedbackCard.tsx`, `useVoiceChat.ts` |

Design rules (from the review's risk list):
- Coaching **never touches the audio path**: reviews run after the turn is finalized, as fire-and-forget tasks.
- Text reviewers cannot hear pronunciation → no pronunciation scores; ASR artifacts are ignored; the learner can remove a wrong correction (false corrections damage trust).
- `summary.good_ratio` is an activity signal, **not** a proficiency score.
- Live-translate sessions are never coached.

## Phase 1 — tutor mode + saved phrases + review (≈1–2 weeks)

1. **Tutor persona**: when coaching is on, inject a tutor system prompt at session start (short replies, one question at a time, ≤1 brief spoken correction, explanations in native language on request). Needs per-provider instruction plumbing — start with DashScope + Google.
2. **Scenarios**: small bilingual catalog (daily chat, workplace, travel, IELTS Part 1/2/3) with objectives and opening prompts.
3. **Saved phrases** (`learning_items`): "save" button on vocabulary/corrections; dedupe by normalized text.
4. **Spaced review** (`learning_review_events`): transparent intervals 1/3/7/14/30 days, "again" resets; review queue with TTS playback of the correct sentence.
5. **Post-call report**: top 3 corrections, new phrases, next objective (also P3 "口语评测卡片" in the earlier roadmap).

## Phase 2 — pronunciation (2–4 weeks)

- Opt-in per-turn learner audio clips + read-aloud / shadowing drills.
- Acoustic assessment via Azure Pronunciation Assessment (Speech SDK is already in `requirements-packaging.lock`).
- Show evidence (clip + recognized text + suggestion) so learners can contest misrecognitions.

## Phase 3 — differentiators

1. **Rehearse tomorrow's real task**: share a slide deck / itinerary via screen share; the tutor runs the interview/negotiation and grades explicit objectives.
2. **Mistake-driven missions**: recurring errors resurface days later in a different scenario, without showing the answer.
3. **Portable learner record across AI providers**: mistakes, phrases and schedules stay local in SQLite while the conversation provider can be swapped freely — something single-vendor apps can't offer.

## Top risks
1. False corrections (ASR errors) → evidence + dismiss + abstain on ambiguity.
2. Async feedback attached to the wrong turn → currently matched by normalized utterance text; move to canonical turn IDs + text hash.
3. Per-turn review doubles inference cost → cap reviews per session; cheap model by default.
4. Learner data is not learner-scoped yet → single local learner until ownership is added.
5. Engagement metrics masquerading as learning → measure delayed recall, not streaks.
