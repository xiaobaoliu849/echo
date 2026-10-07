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

## Phase 1a — shipped: Tutor mode

The realtime model itself becomes a language partner (short replies, one question per turn,
≤1 recast-style spoken correction, native-language help on request, no emoji since replies are spoken).

| Piece | Where |
|---|---|
| Scenarios (free talk, daily life, workplace, travel, job interview, IELTS mock with Part 1/2/3) + tutor prompt | `TUTOR_SCENARIOS`, `build_tutor_instructions` in `backend/services/speaking_coach.py` |
| Per-session binding: WS query params `tutor`, `tutor_language`, `tutor_native_language`, `tutor_level`, `tutor_scenario` → `ContextVar` set in `routers/voice_chat.py` before the provider connects; `_get_base_instructions()` appends the block, so every provider built on it (DashScope, Google, OpenAI, Doubao, StepFun, Vercel, Cartesia, Gradium) gets it with no per-provider code | `routers/voice_chat.py`, `realtime_voice_service.py` |
| UI: 陪练模式 checkbox + 练习场景 select (shares language/level with the coach); applies at next call start | `VoiceCallSettingsPopover.tsx` |

Not covered: local PersonaPlex / GLM-4-Voice (own prompts) and live-translate sessions.

## Phase 1b — shipped: saved phrases + spaced review

| Piece | Where |
|---|---|
| `learning_items` (dedupe on language+kind+normalized text) and `learning_review_events` tables; fixed schedule 1/3/7/14/30/60 days, "again" resets to 1 day, new items due immediately; "learned" = step ≥ 3 | `backend/services/learning_service.py` |
| REST: `POST/GET /api/learning/items`, `DELETE /api/learning/items/{id}`, `GET /api/learning/reviews/due`, `POST /api/learning/reviews`, `GET /api/learning/stats` | `backend/routers/learning.py` |
| "＋ 收藏" on coach cards: corrected sentence (kind `sentence`, context = what the learner said) and each useful phrase (kind `phrase`, meaning + example) | `CoachFeedbackCard.tsx`, `useVoiceChat.ts` (`onSaveCoachItem` uses the practice language) |
| 复习 tab: stats, active-recall cards (phrase: native meaning → say it; sentence: original mistake → fix it), reveal, Edge TTS playback, 没记住/记住了, keyboard Space / 1 / 2, saved-list with delete | `frontend/src/pages/ReviewPage.tsx` |

## Phase 1c — next

1. **Bring reviews into conversation**: at call start in tutor mode, inject 3–5 due phrases and ask the tutor to create chances to use them (prompted recall ≠ independent use — track separately).
2. **Speak the answer**: record the learner's attempt on a review card and compare via ASR instead of self-grading.
3. **Post-call report**: top 3 corrections, new phrases, next objective (also P3 "口语评测卡片" in the earlier roadmap).

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
