export type VoiceInfo = {
  name: string;
  short_name: string;
  locale: string;
  gender: string;
};

export type VoicesResponse = {
  count: number;
  voices: VoiceInfo[];
};

export type TtsAudioResponse = {
  blob: Blob;
  memorySaved: boolean;
  voice?: string;
  engine?: string;
};

export type TtsEngine = "edge" | "qwen_flash" | "minimax" | "xiaomi" | "openai" | "elevenlabs" | "chattts" | "gpt_sovits" | "doubao" | "cartesia";

export type ChatAttachment = {
  name: string;
  content: string;
  type?: "text" | "image" | "pdf" | "audio" | "file";
  mimeType?: string;
  dataUrl?: string;
  url?: string;
  size?: number;
};

export type VoiceAgentSource = {
  title: string;
  uri: string;
  snippet: string;
  source_type: string;
  score?: number;
};

export type VoiceAgentArtifact = {
  type: string;
  run_id?: number;
  agent_run_id?: string;
  status?: string;
  topic?: string;
  current_step?: string;
  source_text?: string;
  target_language?: string;
  translated_text?: string;
  transcript_excerpt?: string;
  summary?: string;
  text?: string;
  audio_path?: string;
  voice?: string;
  engine?: string;
  rate?: string;
  cache_hit?: boolean;
  provider?: string;
  model?: string;
};

export type VoiceAgentToolRecord = {
  status:
    | "started"
    | "progress"
    | "completed"
    | "failed"
    | "cancelled"
    | "context_injected"
    | "result_delivered"
    | "delivery_failed"
    | "response_gated"
    | "result";
  tool_name?: string;
  turn_id?: string;
  tool_call_id?: string;
  provider_call_id?: string;
  route?: "native" | "compatibility";
  query?: string;
  message?: string;
  answer?: string;
  source_count?: number;
  elapsed_ms?: number;
  reason?: string;
  provider?: string;
  stage?: string;
  sources?: VoiceAgentSource[];
  artifact?: VoiceAgentArtifact;
};

export type VoiceAgentSessionHistory = {
  id: string;
  provider: string;
  model: string;
  voice: string;
  status: string;
  started_at: string;
  ended_at?: string;
  meta?: Record<string, unknown>;
};

export type VoiceAgentTurnHistory = {
  id: number;
  session_id: string;
  turn_id: string;
  user_text: string;
  assistant_text: string;
  memory_payload?: Record<string, unknown>;
  completed: boolean;
  interrupted?: boolean;
  completion_status?: "pending" | "in_progress" | "completed" | "interrupted" | string;
  started_at: string;
  completed_at?: string;
};

export type VoiceAgentToolEventHistory = {
  id: number;
  session_id: string;
  turn_id: string;
  event_type: string;
  tool_name: string;
  query: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type VoiceAgentTimelineEventHistory = {
  id: string;
  event_type: string;
  source: string;
  turn_id: string;
  tool_name: string;
  query: string;
  text: string;
  timestamp: string;
  payload: Record<string, unknown>;
  elapsed_ms?: number;
  provider?: string;
  transport?: string;
  stage?: string;
  sequence_no?: number;
};

export type VoiceAgentSessionHistoryListResponse = {
  count: number;
  sessions: VoiceAgentSessionHistory[];
};

export type AgentRunSummary = {
  id: string;
  run_type: string;
  source_kind: string;
  source_run_id: string;
  title: string;
  status: string;
  current_step: string;
  provider: string;
  model: string;
  input_payload?: Record<string, unknown>;
  result_payload?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at?: string;
};

export type VoiceAgentRunLink = {
  id: number;
  agent_run_id: string;
  voice_session_id: string;
  voice_turn_id: string;
  relation_type: string;
  meta?: Record<string, unknown>;
  created_at: string;
  run: AgentRunSummary;
};

export type MetricDistribution = {
  count: number;
  avg: number | null;
  p50: number | null;
  p95: number | null;
  min: number | null;
  max: number | null;
};

export type VoiceAgentMetricBreakdown = {
  provider: string;
  session_count: number;
  turn_count: number;
  completed_turn_count: number;
  interrupted_turn_count: number;
  decision_count: number;
  classifications: Record<string, number>;
  false_interruption_rate: number | null;
  first_audio_ms: MetricDistribution;
  interruption_decision_ms: MetricDistribution;
  interruption_stop_ms: MetricDistribution;
  turn_completion_ms: MetricDistribution;
};

export type VoiceAgentMetricsSummary = VoiceAgentMetricBreakdown & {
  providers: VoiceAgentMetricBreakdown[];
};

export type VoiceAgentSessionHistoryDetailResponse = VoiceAgentSessionHistory & {
  turns: VoiceAgentTurnHistory[];
  tool_events: VoiceAgentToolEventHistory[];
  timeline: VoiceAgentTimelineEventHistory[];
  agent_run_links?: VoiceAgentRunLink[];
};

export type ChatMessage = {
  role: "system" | "user" | "assistant";
  content: string;
  reasoningContent?: string;
  attachments?: ChatAttachment[];
  memoriesUsed?: number;
  memorySaved?: boolean;
  memorySourceSummary?: string;
  memoryRetrievalAttempted?: boolean;
  toolCalls?: VoiceAgentToolRecord[];
  turnId?: string;
  interrupted?: boolean;
  /** Stable client-side identity used for React keys and per-message UI state. */
  id?: string;
};

export type ChatRequest = {
  provider: string;
  model?: string;
  messages: ChatMessage[];
  temperature?: number;
  max_tokens?: number;
  use_memory?: boolean;
  deep_thinking?: boolean;
};

export type ChatResponse = {
  provider: string;
  model: string;
  reply: string;
  raw: Record<string, unknown>;
};

export type EverMemConversationMetaResponse = {
  group_id: string;
  user_id?: string;
};

export type StreamEventHandlers = {
  onDelta: (chunk: string) => void;
  onReasoning?: (chunk: string) => void;
  onDone?: (meta?: { memoriesRetrieved: number; memorySaved: boolean }) => void;
};

export type TranslateRequest = {
  text: string;
  target_language: string;
  source_language?: string;
  provider?: string;
  model?: string;
};

export type TranslateResponse = {
  provider: string;
  model: string;
  translated_text: string;
};

export type VoiceType = "voice_design" | "voice_clone";

export type CustomVoice = {
  voice: string;
  type: VoiceType;
  target_model: string;
  language?: string;
  name?: string;
  gender?: string;
};

export type CustomVoiceListResponse = {
  voice_type: VoiceType;
  count: number;
  voices: CustomVoice[];
};

export type VoiceDesignRequest = {
  voice_prompt: string;
  preview_text: string;
  preferred_name: string;
  language?: string;
  provider?: string;
};

export type VoiceCreateResponse = {
  voice?: string;
  type: VoiceType;
  target_model?: string;
  preferred_name?: string;
  language?: string;
  preview_audio_data?: string;
  provider?: string;
};

export type SettingsModelValue =
  | string
  | {
    default?: string;
    available?: string[];
    enabled?: string[];
  };

export type AppSettings = {
  api_keys: Record<string, string>;
  api_urls: Record<string, string>;
  realtime_api_urls?: Record<string, string>;
  default_models: Record<string, SettingsModelValue>;
  general_settings: Record<string, unknown>;
  memory_settings: Record<string, unknown>;
  output_directory: string;
  tts_settings: Record<string, unknown>;
  qwen_tts_settings: Record<string, unknown>;
  transcription_settings: Record<string, unknown>;
  minimax: Record<string, unknown>;
  xiaomi: Record<string, unknown>;
  ui_settings: Record<string, unknown>;
  shortcuts: Record<string, unknown>;
  custom_providers?: any[];
};

export type SettingsResponse = {
  config_path: string;
  providers: string[];
  settings: AppSettings;
};

export type DesktopStatusResponse = {
  runtime_dir: string;
  diagnostics_dir: string;
  preflight: {
    available: boolean;
    ok: boolean | null;
    timestamp: string;
    failed_checks: Array<{ name: string; detail: string }>;
    failed_count: number;
  };
  latest_error: {
    available: boolean;
    timestamp: string;
    error_type: string;
    message: string;
    recovery_hints: string[];
  };
};

export type AudioOverviewScriptLine = {
  role: string;
  text: string;
};

export type AudioOverviewPodcast = {
  id: number;
  topic: string;
  language: string;
  audio_path: string | null;
  created_at: string;
  updated_at: string;
  script_lines: AudioOverviewScriptLine[];
};

export type AudioOverviewPodcastListResponse = {
  count: number;
  podcasts: AudioOverviewPodcast[];
};

export type AudioOverviewScriptGenerateRequest = {
  topic: string;
  language?: string;
  turn_count?: number;
  provider?: string;
  model?: string;
};

export type AudioOverviewScriptGenerateResponse = {
  topic: string;
  language: string;
  turn_count: number;
  provider: string;
  model: string;
  script_lines: AudioOverviewScriptLine[];
  memories_retrieved?: number;
  memory_saved?: boolean;
};

export type AudioOverviewSynthesizeRequest = {
  voice_a?: string;
  voice_b?: string;
  rate?: string;
  language?: string;
  gap_ms?: number;
  merge_strategy?: "auto" | "pydub" | "ffmpeg" | "concat";
  intro_music?: boolean;
  intro_music_style?: "warm" | "bright" | "calm";
  intro_music_duration_ms?: number;
};

export type AudioOverviewSynthesizeResponse = {
  podcast_id: number;
  audio_path: string;
  audio_download_url: string;
  line_count: number;
  voice_a: string;
  voice_b: string;
  rate: string;
  cache_hits: number;
  gap_ms: number;
  gap_ms_applied: number;
  merge_strategy: string;
  intro_music: boolean;
  intro_music_style: string;
  intro_music_duration_ms: number;
};

export type AudioAgentStep = {
  id: number;
  run_id: number;
  step_name: string;
  status: string;
  attempt_index: number;
  started_at: string;
  finished_at: string;
  meta: Record<string, unknown>;
  error_code: string;
  error_message: string;
};

export type AudioAgentSource = {
  id: number;
  run_id: number;
  source_type: string;
  title: string;
  uri: string;
  snippet: string;
  content: string;
  score: number;
  meta: Record<string, unknown>;
  created_at: string;
};

export type AudioAgentEvent = {
  id: number;
  run_id: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type AudioAgentRun = {
  id: number;
  podcast_id: number | null;
  topic: string;
  language: string;
  status: string;
  current_step: string;
  provider: string;
  model: string;
  use_memory: boolean;
  input_payload: Record<string, unknown>;
  result_payload: Record<string, unknown>;
  error_code: string;
  error_message: string;
  created_at: string;
  updated_at: string;
  completed_at: string;
};

export type AudioAgentRunDetail = AudioAgentRun & {
  steps: AudioAgentStep[];
  sources: AudioAgentSource[];
};

export type AudioAgentRunListResponse = {
  count: number;
  runs: AudioAgentRun[];
};

export type AudioAgentEventListResponse = {
  count: number;
  events: AudioAgentEvent[];
};

export type AudioAgentCreateRunRequest = {
  topic: string;
  language?: string;
  provider?: string;
  model?: string;
  use_memory?: boolean;
  source_urls?: string[];
  source_text?: string;
  generation_constraints?: string;
  turn_count?: number;
  auto_execute?: boolean;
};

export type AudioAgentSynthesizeRequest = {
  voice_a?: string;
  voice_b?: string;
  rate?: string;
  language?: string;
  gap_ms?: number;
  merge_strategy?: "auto" | "pydub" | "ffmpeg" | "concat";
  intro_music?: boolean;
  intro_music_style?: "warm" | "bright" | "calm";
  intro_music_duration_ms?: number;
};

export type ApiRuntimeInfo = {
  name?: string;
  version?: string;
  status?: string;
  phase?: string;
  auth_enabled?: boolean;
  auth_mode?: string;
  raw?: Record<string, unknown>;
};

export type AuthUser = {
  id: string;
  email: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
};

export type AuthSessionResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export type ApiErrorDetail = {
  code?: string;
  message?: string;
  meta?: Record<string, unknown>;
};

export type WordTimestamp = {
  text: string;
  start: number;
  end: number;
};

export type TranscriptionResponse = {
  transcript: string;
  job_id?: string;
  source_url?: string | null;
  memory_saved?: boolean;
  duration_seconds?: number | null;
  words?: WordTimestamp[] | null;
  provider?: string | null;
};

export type TranscriptionJobResponse = {
  job_id: string;
  remote_job_id?: string | null;
  mode: string;
  status: string;
  file_name: string;
  created_at?: string | null;
  updated_at?: string | null;
  transcript?: string | null;
  has_transcript?: boolean;
  transcript_download_url?: string | null;
  source_url?: string | null;
  error?: string | null;
  memory_saved?: boolean;
  provider?: string | null;
  /** Progress line for local chunked jobs, e.g. "正在转写第 3/12 段…". */
  progress?: string | null;
};

export type TranscriptionJobListResponse = {
  count: number;
  jobs: TranscriptionJobResponse[];
};

export type TranscriptionBatchDeleteResponse = {
  deleted: string[];
  failed: string[];
  deleted_count: number;
  failed_count: number;
};

export type VoiceChatServerEvent =
  | {
      type: "session_open";
      provider: string;
      model: string;
      voice: string;
      session_id?: string;
      mode?: "realtime_chat" | "live_translate";
      target_language_code?: string;
      echo_target_language?: boolean;
    }
  | { type: "memory_config"; enabled: boolean; scope: string; group_id?: string }
  | {
      type: "memory_context";
      memories_retrieved: number;
      local_pending_count?: number;
      cloud_count?: number;
      attempted?: boolean;
    }
  | {
      type: "memory_write";
      attempted_count: number;
      saved_count: number;
      failed_count: number;
      local_pending_count?: number;
      reason?: string;
    }
  | { type: "user_transcript"; text: string; turn_id?: string; tentative?: string; final?: boolean; interim?: boolean }
  | { type: "translation_preview"; text?: string; tentative?: string; turn_id?: string }
  | { type: "assistant_text"; text: string; turn_id?: string }
  | {
      type: "assistant_audio";
      audio: string;
      encoding: string;
      sample_rate: number;
      turn_id?: string;
      first_audio_ms?: number;
    }
  | {
      type: "interruption_pending";
      candidate_id: string;
      provider: string;
      interrupted_turn_id?: string;
      provider_event_type?: string;
    }
  | {
      type: "interruption_decision";
      candidate_id: string;
      classification: "TRUE_BARGE_IN" | "BACKCHANNEL" | "NOISE_OR_SILENCE";
      rule: string;
      decision: "cancel" | "resume" | "ignore";
      transcript: string;
      provider: string;
      interrupted_turn_id?: string;
      provider_event_type?: string;
      elapsed_ms: number;
      decision_latency_ms?: number;
      stop_latency_ms?: number;
      assistant_interrupted?: boolean;
      provider_cancel_requested?: boolean;
      tool_cancelled?: boolean;
    }
  | {
      type: "interrupted";
      candidate_id?: string;
      turn_id?: string;
      interrupted?: boolean;
      stop_latency_ms?: number;
    }
  | {
      type: "tool_call_started";
      tool_name: string;
      turn_id?: string;
      tool_call_id?: string;
      provider_call_id?: string;
      route?: "native" | "compatibility";
      query?: string;
      message?: string;
    }
  | {
      type: "agent_progress";
      stage: string;
      turn_id?: string;
      tool_call_id?: string;
      provider_call_id?: string;
      route?: "native" | "compatibility";
      message: string;
      elapsed_ms?: number;
    }
  | {
      type: "tool_call_completed";
      tool_name: string;
      turn_id?: string;
      query?: string;
      source_count?: number;
      sources?: VoiceAgentSource[];
      elapsed_ms?: number;
      tool_call_id?: string;
      provider_call_id?: string;
      route?: "native" | "compatibility";
    }
  | {
      type: "tool_call_failed";
      tool_name: string;
      turn_id?: string;
      query?: string;
      message: string;
      elapsed_ms?: number;
      tool_call_id?: string;
      provider_call_id?: string;
      route?: "native" | "compatibility";
    }
  | {
      type: "tool_call_cancelled";
      tool_name: string;
      turn_id?: string;
      query?: string;
      reason?: string;
      elapsed_ms?: number;
      tool_call_id?: string;
      provider_call_id?: string;
      route?: "native" | "compatibility";
    }
  | {
      type: "tool_context_injected";
      provider: string;
      tool_name: string;
      turn_id?: string;
      query?: string;
      source_count?: number;
      sources?: VoiceAgentSource[];
      elapsed_ms?: number;
    }
  | {
      type: "tool_result_delivered";
      provider: string;
      tool_name: string;
      turn_id?: string;
      tool_call_id?: string;
      provider_call_id: string;
      route: "native";
      query?: string;
      source_count?: number;
      sources?: VoiceAgentSource[];
      elapsed_ms?: number;
      status: "completed" | "failed";
    }
  | {
      type: "tool_result_delivery_failed";
      tool_name: string;
      turn_id?: string;
      tool_call_id?: string;
      provider_call_id?: string;
      query?: string;
      message: string;
      route?: "native" | "compatibility";
    }
  | {
      type: "response_gated";
      provider: string;
      tool_name: string;
      turn_id?: string;
      tool_call_id?: string;
      provider_call_id?: string;
      query?: string;
      message?: string;
    }
  | {
      type: "agent_result";
      tool_name?: string;
      query: string;
      turn_id?: string;
      tool_call_id?: string;
      provider_call_id?: string;
      route?: "native" | "compatibility";
      answer: string;
      source_count?: number;
      elapsed_ms?: number;
      artifact?: VoiceAgentArtifact;
      sources: VoiceAgentSource[];
    }
  | { type: "turn_complete"; turn_id?: string; interrupted?: boolean }
  | { type: "pong" }
  | { type: "error"; message: string; provider?: string };

