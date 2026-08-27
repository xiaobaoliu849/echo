import type {
  AgentRunSummary,
  ApiErrorDetail,
  ApiRuntimeInfo,
  AudioAgentCreateRunRequest,
  AudioAgentEventListResponse,
  AudioAgentRunDetail,
  AudioAgentRunListResponse,
  AudioAgentSynthesizeRequest,
  AudioOverviewPodcast,
  AudioOverviewPodcastListResponse,
  AudioOverviewScriptGenerateRequest,
  AudioOverviewScriptGenerateResponse,
  AudioOverviewScriptLine,
  AudioOverviewSynthesizeRequest,
  AudioOverviewSynthesizeResponse,
  AuthSessionResponse,
  AuthUser,
  BurnVideoResponse,
  ChatRequest,
  ChatResponse,
  CustomVoiceListResponse,
  DesktopStatusResponse,
  EverMemConversationMetaResponse,
  SettingsResponse,
  StreamEventHandlers,
  SubtitleCueItem,
  TranscriptionBatchDeleteResponse,
  TranscriptionJobListResponse,
  TranscriptionJobResponse,
  TranscriptionResponse,
  TranslateJobResponse,
  TranslateRequest,
  WordTimestamp,
  TranslateResponse,
  TtsAudioResponse,
  TtsEngine,
  VoiceAgentMetricsSummary,
  VoiceAgentSessionHistoryDetailResponse,
  VoiceAgentSessionHistoryListResponse,
  VoiceCreateResponse,
  VoiceDesignRequest,
  VoiceType,
  VoicesResponse
} from "./types";

export class ApiRequestError extends Error {
  status: number;
  detail?: ApiErrorDetail;

  constructor(message: string, status: number, detail?: ApiErrorDetail) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
  }
}

export const API_BASE_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
export const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";
export const API_ADMIN_TOKEN = import.meta.env.VITE_API_ADMIN_TOKEN || "";
const API_TOKEN_STORAGE_KEY = "voicespirit_api_token";
const API_ADMIN_TOKEN_STORAGE_KEY = "voicespirit_api_admin_token";
const AUTH_USER_EMAIL_STORAGE_KEY = "voicespirit_auth_user_email";
const AUTH_USER_ADMIN_STORAGE_KEY = "voicespirit_auth_user_admin";
const CLIENT_ID_STORAGE_KEY = "voicespirit_client_id";
const EVERMEM_ENABLED_STORAGE_KEY = "evermem_enabled";
const EVERMEM_API_URL_STORAGE_KEY = "evermem_api_url";
const EVERMEM_SCOPE_ID_STORAGE_KEY = "evermem_scope_id";
const EVERMEM_TEMP_SESSION_STORAGE_KEY = "evermem_temporary_session";
const EVERMEM_REMEMBER_CHAT_STORAGE_KEY = "evermem_remember_chat";
const EVERMEM_REMEMBER_VOICE_CHAT_STORAGE_KEY = "evermem_remember_voice_chat";
const EVERMEM_REMEMBER_RECORDINGS_STORAGE_KEY = "evermem_remember_recordings";
const EVERMEM_REMEMBER_PODCAST_STORAGE_KEY = "evermem_remember_podcast";
const EVERMEM_REMEMBER_TTS_STORAGE_KEY = "evermem_remember_tts";
const EVERMEM_STORE_TRANSCRIPT_FULLTEXT_STORAGE_KEY = "evermem_store_transcript_fulltext";
const EVERMEM_LEGACY_KEY_STORAGE_KEY = "evermem_key";
const EVERMEM_CHAT_GROUP_ID_STORAGE_KEY = "evermem_chat_group_id";
const EVERMEM_VOICE_CHAT_GROUP_ID_STORAGE_KEY = "evermem_voice_chat_group_id";

let evermemRuntimeKey = "";

export type AuthRuntimeConfig = {
  apiToken: string;
  adminToken: string;
  userEmail: string;
  isAdmin: boolean;
  hasEnvApiToken: boolean;
  hasEnvAdminToken: boolean;
};

function safeStorageGet(key: string): string {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function safeStorageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Ignore storage failures in non-browser contexts.
  }
}

function safeStorageRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Ignore storage failures in non-browser contexts.
  }
}

function createClientId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `vs-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function getClientId(): string {
  const existing = safeStorageGet(CLIENT_ID_STORAGE_KEY).trim();
  if (existing) {
    return existing;
  }
  const next = createClientId();
  safeStorageSet(CLIENT_ID_STORAGE_KEY, next);
  return next;
}

function getStoredApiToken(): string {
  return safeStorageGet(API_TOKEN_STORAGE_KEY).trim();
}

function getStoredAdminToken(): string {
  return safeStorageGet(API_ADMIN_TOKEN_STORAGE_KEY).trim();
}

function getStoredUserEmail(): string {
  return safeStorageGet(AUTH_USER_EMAIL_STORAGE_KEY).trim();
}

function getStoredUserAdmin(): boolean {
  return safeStorageGet(AUTH_USER_ADMIN_STORAGE_KEY) === "true";
}

function resolveAuthToken(useAdminToken: boolean): string {
  if (useAdminToken) {
    return getStoredAdminToken() || getStoredApiToken() || API_ADMIN_TOKEN || API_TOKEN;
  }
  return getStoredApiToken() || API_TOKEN;
}

// Browsers cannot set custom headers on the WebSocket handshake, so realtime
// endpoints accept the bearer token as a `token` query parameter instead.
// The backend validates it exactly like an Authorization header (and ignores
// it when auth is disabled). Falls back to the admin token so admin-only
// deployments still connect.
export function getRealtimeWebSocketToken(): string {
  return getStoredApiToken() || getStoredAdminToken() || API_TOKEN || API_ADMIN_TOKEN;
}

export function getAuthRuntimeConfig(): AuthRuntimeConfig {
  return {
    apiToken: getStoredApiToken(),
    adminToken: getStoredAdminToken(),
    userEmail: getStoredUserEmail(),
    isAdmin: getStoredUserAdmin(),
    hasEnvApiToken: Boolean(API_TOKEN),
    hasEnvAdminToken: Boolean(API_ADMIN_TOKEN),
  };
}

export function configureAuthRuntime(config: {
  apiToken?: string;
  adminToken?: string;
  userEmail?: string;
  isAdmin?: boolean;
}): AuthRuntimeConfig {
  const apiToken = (config.apiToken || "").trim();
  const adminToken = (config.adminToken || "").trim();
  const userEmail = (config.userEmail || "").trim();
  if (apiToken) {
    safeStorageSet(API_TOKEN_STORAGE_KEY, apiToken);
  } else {
    safeStorageRemove(API_TOKEN_STORAGE_KEY);
  }
  if (adminToken) {
    safeStorageSet(API_ADMIN_TOKEN_STORAGE_KEY, adminToken);
  } else {
    safeStorageRemove(API_ADMIN_TOKEN_STORAGE_KEY);
  }
  if (userEmail) {
    safeStorageSet(AUTH_USER_EMAIL_STORAGE_KEY, userEmail);
  } else {
    safeStorageRemove(AUTH_USER_EMAIL_STORAGE_KEY);
  }
  safeStorageSet(AUTH_USER_ADMIN_STORAGE_KEY, String(config.isAdmin === true));
  return getAuthRuntimeConfig();
}

export function clearAuthRuntime(): AuthRuntimeConfig {
  safeStorageRemove(API_TOKEN_STORAGE_KEY);
  safeStorageRemove(API_ADMIN_TOKEN_STORAGE_KEY);
  safeStorageRemove(AUTH_USER_EMAIL_STORAGE_KEY);
  safeStorageRemove(AUTH_USER_ADMIN_STORAGE_KEY);
  return getAuthRuntimeConfig();
}

function applyAuthSession(session: AuthSessionResponse): AuthRuntimeConfig {
  const token = String(session.access_token || "").trim();
  const user = session.user;
  return configureAuthRuntime({
    apiToken: token,
    adminToken: user?.is_admin ? token : "",
    userEmail: String(user?.email || "").trim(),
    isAdmin: Boolean(user?.is_admin),
  });
}

export function configureEverMemRuntime(config: {
  enabled: boolean;
  api_url: string;
  api_key?: string;
  scope_id?: string;
  temporary_session?: boolean;
  remember_chat?: boolean;
  remember_voice_chat?: boolean;
  remember_recordings?: boolean;
  remember_podcast?: boolean;
  remember_tts?: boolean;
  store_transcript_fulltext?: boolean;
}): void {
  safeStorageSet(EVERMEM_ENABLED_STORAGE_KEY, String(config.enabled));
  safeStorageSet(EVERMEM_API_URL_STORAGE_KEY, config.api_url.trim());
  safeStorageSet(EVERMEM_SCOPE_ID_STORAGE_KEY, (config.scope_id || "").trim());
  safeStorageSet(EVERMEM_TEMP_SESSION_STORAGE_KEY, String(config.temporary_session ?? false));
  safeStorageSet(EVERMEM_REMEMBER_CHAT_STORAGE_KEY, String(config.remember_chat ?? true));
  safeStorageSet(EVERMEM_REMEMBER_VOICE_CHAT_STORAGE_KEY, String(config.remember_voice_chat ?? true));
  safeStorageSet(EVERMEM_REMEMBER_RECORDINGS_STORAGE_KEY, String(config.remember_recordings ?? true));
  safeStorageSet(EVERMEM_REMEMBER_PODCAST_STORAGE_KEY, String(config.remember_podcast ?? true));
  safeStorageSet(EVERMEM_REMEMBER_TTS_STORAGE_KEY, String(config.remember_tts ?? false));
  safeStorageSet(EVERMEM_STORE_TRANSCRIPT_FULLTEXT_STORAGE_KEY, String(config.store_transcript_fulltext ?? false));

  safeStorageRemove(EVERMEM_LEGACY_KEY_STORAGE_KEY);
  evermemRuntimeKey = (config.api_key || "").trim();
}

export function getEverMemRuntimeConfig() {
  return {
    enabled: safeStorageGet(EVERMEM_ENABLED_STORAGE_KEY) === "true",
    api_url: safeStorageGet(EVERMEM_API_URL_STORAGE_KEY),
    api_key: evermemRuntimeKey,
    scope_id: safeStorageGet(EVERMEM_SCOPE_ID_STORAGE_KEY),
    temporary_session: safeStorageGet(EVERMEM_TEMP_SESSION_STORAGE_KEY) === "true",
    remember_chat: safeStorageGet(EVERMEM_REMEMBER_CHAT_STORAGE_KEY) !== "false", // Default true
    remember_voice_chat: safeStorageGet(EVERMEM_REMEMBER_VOICE_CHAT_STORAGE_KEY) !== "false", // Default true
    remember_recordings: safeStorageGet(EVERMEM_REMEMBER_RECORDINGS_STORAGE_KEY) !== "false", // Default true
    remember_podcast: safeStorageGet(EVERMEM_REMEMBER_PODCAST_STORAGE_KEY) !== "false", // Default true
    remember_tts: safeStorageGet(EVERMEM_REMEMBER_TTS_STORAGE_KEY) === "true", // Default false
    store_transcript_fulltext: safeStorageGet(EVERMEM_STORE_TRANSCRIPT_FULLTEXT_STORAGE_KEY) === "true",
  };
}

export type EverMemScene = "chat" | "voice_chat" | "transcription" | "podcast" | "tts";
type EverMemConversationScene = Extract<EverMemScene, "chat" | "voice_chat">;

type EverMemSceneConfig = {
  enabled: true;
  api_url: string;
  api_key?: string;
  scope_id?: string;
  group_id?: string;
};

type EverMemHeaderOptions = {
  groupId?: string;
  /**
   * Bypass the per-scene "remember_*" auto toggle. Used for deliberate,
   * user-initiated saves (e.g. "save this transcript to memory") where the
   * global auto-save switch should not veto an explicit action. The global
   * `enabled` / `temporary_session` gates still apply.
   */
  forceScene?: boolean;
};

function buildEverMemSceneConfig(
  useMemory: boolean,
  scene?: EverMemScene,
  options: EverMemHeaderOptions = {}
): EverMemSceneConfig | null {
  if (!useMemory) {
    return null;
  }
  const evermem = getEverMemRuntimeConfig();
  if (!evermem.enabled || evermem.temporary_session) {
    return null;
  }
  if (!options.forceScene) {
    if (scene === "chat" && !evermem.remember_chat) return null;
    if (scene === "voice_chat" && !evermem.remember_voice_chat) return null;
    if (scene === "transcription" && !evermem.remember_recordings) return null;
    if (scene === "podcast" && !evermem.remember_podcast) return null;
    if (scene === "tts" && !evermem.remember_tts) return null;
  }
  const resolvedScopeId = evermem.scope_id || `client:${getClientId()}`;

  return {
    enabled: true,
    api_url: evermem.api_url || "",
    ...(evermem.api_key ? { api_key: evermem.api_key } : {}),
    ...(resolvedScopeId ? { scope_id: resolvedScopeId } : {}),
    ...(options.groupId ? { group_id: options.groupId } : {}),
  };
}

function buildEverMemHeaders(
  useMemory: boolean,
  scene?: EverMemScene,
  options: EverMemHeaderOptions = {}
): Record<string, string> {
  const config = buildEverMemSceneConfig(useMemory, scene, options);
  if (!config) {
    return {};
  }
  return {
    "X-EverMem-Enabled": "true",
    "X-EverMem-Url": config.api_url,
    ...(config.api_key ? { "X-EverMem-Key": config.api_key } : {}),
    ...(config.scope_id ? { "X-EverMem-Scope": config.scope_id } : {}),
    ...(config.group_id ? { "X-EverMem-Group-ID": config.group_id } : {}),
  };
}

export function buildVoiceChatSessionConfig(groupId?: string): EverMemSceneConfig | null {
  return buildEverMemSceneConfig(true, "voice_chat", { groupId });
}

function resolveEverMemConversationGroupStorageKey(scene: EverMemConversationScene): string {
  return scene === "voice_chat"
    ? EVERMEM_VOICE_CHAT_GROUP_ID_STORAGE_KEY
    : EVERMEM_CHAT_GROUP_ID_STORAGE_KEY;
}

export function getPersistedEverMemConversationGroupId(scene: EverMemConversationScene): string {
  return safeStorageGet(resolveEverMemConversationGroupStorageKey(scene)).trim();
}

export function persistEverMemConversationGroupId(
  scene: EverMemConversationScene,
  groupId: string
): string {
  const normalized = (groupId || "").trim();
  const storageKey = resolveEverMemConversationGroupStorageKey(scene);
  if (!normalized) {
    safeStorageRemove(storageKey);
    return "";
  }
  safeStorageSet(storageKey, normalized);
  return normalized;
}

export function clearPersistedEverMemConversationGroupId(scene: EverMemConversationScene): void {
  safeStorageRemove(resolveEverMemConversationGroupStorageKey(scene));
}

export async function createEverMemConversationMeta(
  scene: EverMemScene,
  groupId?: string
): Promise<EverMemConversationMetaResponse | null> {
  const normalizedGroupId = (groupId || "").trim();
  const headers = buildEverMemHeaders(
    true,
    scene,
    normalizedGroupId ? { groupId: normalizedGroupId } : {}
  );
  if (headers["X-EverMem-Enabled"] !== "true") {
    return null;
  }
  const response = await apiFetch(`${API_BASE_URL}/api/evermem/conversation-meta`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(normalizedGroupId ? { group_id: normalizedGroupId } : {}),
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  const payload = (await response.json()) as Partial<EverMemConversationMetaResponse>;
  const resolvedGroupId = typeof payload.group_id === "string" ? payload.group_id.trim() : "";
  if (!resolvedGroupId) {
    throw new Error("EverMem conversation meta response is missing group_id.");
  }
  return {
    group_id: resolvedGroupId,
    ...(typeof payload.user_id === "string" && payload.user_id.trim()
      ? { user_id: payload.user_id.trim() }
      : {}),
  };
}

export async function ensureEverMemConversationGroupId(
  scene: EverMemScene,
  currentGroupId?: string
): Promise<string> {
  if (!buildEverMemSceneConfig(true, scene)) {
    return "";
  }
  const existing = (currentGroupId || "").trim();
  if (existing) {
    return existing;
  }
  const meta = await createEverMemConversationMeta(scene);
  return meta?.group_id || "";
}

function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: { useAdminToken?: boolean } = {}
): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const token = resolveAuthToken(options.useAdminToken === true);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!headers.has("X-Client-ID")) {
    headers.set("X-Client-ID", getClientId());
  }
  return fetch(input, { ...init, headers });
}

// Deduplicates concurrent identical idempotent GETs and caches the parsed JSON
// for a short TTL, so voice catalogs / static lists are not re-fetched on every
// hook mount or engine switch within a session.
const GET_CACHE_TTL_MS = 60_000;
const idempotentGetCache = new Map<string, { promise: Promise<unknown>; expires: number }>();

function cachedGetJson<T>(
  url: string,
  init: RequestInit = {},
  options: { useAdminToken?: boolean } = {}
): Promise<T> {
  const now = Date.now();
  const cached = idempotentGetCache.get(url);
  if (cached && cached.expires > now) {
    return cached.promise as Promise<T>;
  }
  const promise = apiFetch(url, init, options)
    .then(async (response) => {
      if (!response.ok) {
        idempotentGetCache.delete(url);
        await throwApiError(response);
      }
      return response.json();
    })
    .catch((err) => {
      idempotentGetCache.delete(url);
      throw err;
    });
  idempotentGetCache.set(url, { promise, expires: now + GET_CACHE_TTL_MS });
  return promise as Promise<T>;
}

export function buildVoiceChatWebSocketUrl(params: {
  provider?: string;
  model?: string;
  voice?: string;
  voiceprintAudioUrls?: string[];
  translationMode?: string;
  sourceLanguageCode?: string;
  targetLanguageCode?: string;
  echoTargetLanguage?: boolean;
  enableVoiceClone?: boolean;
  voiceCloneFrequency?: string;
}): string {
  const httpUrl = new URL(API_BASE_URL);
  const protocol = httpUrl.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = new URL(`${protocol}//${httpUrl.host}/api/voice-chat/ws`);
  if (params.provider) {
    wsUrl.searchParams.set("provider", params.provider);
  }
  if (params.model) {
    wsUrl.searchParams.set("model", params.model);
  }
  if (params.voice) {
    wsUrl.searchParams.set("voice", params.voice);
  }
  if (Array.isArray(params.voiceprintAudioUrls)) {
    params.voiceprintAudioUrls
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 5)
      .forEach((item) => wsUrl.searchParams.append("voiceprint_audio_urls", item));
  }
  if (params.translationMode) {
    wsUrl.searchParams.set("translation_mode", params.translationMode);
  }
  if (params.sourceLanguageCode) {
    wsUrl.searchParams.set("source_language_code", params.sourceLanguageCode);
  }
  if (params.targetLanguageCode) {
    wsUrl.searchParams.set("target_language_code", params.targetLanguageCode);
  }
  if (typeof params.echoTargetLanguage === "boolean") {
    wsUrl.searchParams.set("echo_target_language", String(params.echoTargetLanguage));
  }
  if (typeof params.enableVoiceClone === "boolean") {
    wsUrl.searchParams.set("enable_voice_clone", String(params.enableVoiceClone));
  }
  if (params.voiceCloneFrequency) {
    wsUrl.searchParams.set("voice_clone_frequency", params.voiceCloneFrequency);
  }
  const wsToken = getRealtimeWebSocketToken();
  if (wsToken) {
    wsUrl.searchParams.set("token", wsToken);
  }
  return wsUrl.toString();
}

export async function listVoiceAgentSessions(
  limit = 20
): Promise<VoiceAgentSessionHistoryListResponse> {
  const normalizedLimit = Number.isFinite(limit) ? Math.floor(limit) : 20;
  const safeLimit = Math.max(1, Math.min(normalizedLimit, 200));
  const response = await apiFetch(
    `${API_BASE_URL}/api/voice-chat/sessions?limit=${encodeURIComponent(String(safeLimit))}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as VoiceAgentSessionHistoryListResponse;
}

export async function fetchVoiceAgentMetricsSummary(
  limit = 200,
  provider = ""
): Promise<VoiceAgentMetricsSummary> {
  const normalizedLimit = Number.isFinite(limit) ? Math.floor(limit) : 200;
  const safeLimit = Math.max(1, Math.min(normalizedLimit, 200));
  const params = new URLSearchParams({ limit: String(safeLimit) });
  if (provider.trim()) {
    params.set("provider", provider.trim());
  }
  const response = await apiFetch(
    `${API_BASE_URL}/api/voice-chat/sessions/metrics/summary?${params.toString()}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as VoiceAgentMetricsSummary;
}

export async function fetchVoiceAgentSession(
  sessionId: string
): Promise<VoiceAgentSessionHistoryDetailResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/voice-chat/sessions/${encodeURIComponent(sessionId)}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as VoiceAgentSessionHistoryDetailResponse;
}

export async function fetchAgentRun(agentRunId: string): Promise<AgentRunSummary> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/agent-runs/${encodeURIComponent(agentRunId)}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as AgentRunSummary;
}

export async function fetchApiRuntimeInfo(): Promise<ApiRuntimeInfo> {
  const response = await apiFetch(`${API_BASE_URL}/`);
  if (!response.ok) {
    await throwApiError(response);
  }
  const data = (await response.json()) as unknown;
  if (!data || typeof data !== "object") {
    return {};
  }
  const obj = data as Record<string, unknown>;
  return {
    name: typeof obj.name === "string" ? obj.name : undefined,
    version: typeof obj.version === "string" ? obj.version : undefined,
    status: typeof obj.status === "string" ? obj.status : undefined,
    phase: typeof obj.phase === "string" ? obj.phase : undefined,
    auth_enabled:
      typeof obj.auth_enabled === "boolean" ? obj.auth_enabled : undefined,
    auth_mode: typeof obj.auth_mode === "string" ? obj.auth_mode : undefined,
    raw: obj
  };
}

export async function loginAuthUser(email: string, password: string): Promise<AuthRuntimeConfig> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Client-ID": getClientId(),
    },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return applyAuthSession((await response.json()) as AuthSessionResponse);
}

export async function registerAuthUser(email: string, password: string): Promise<AuthRuntimeConfig> {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Client-ID": getClientId(),
    },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return applyAuthSession((await response.json()) as AuthSessionResponse);
}

export async function fetchCurrentAuthUser(): Promise<AuthRuntimeConfig> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/me`);
  if (!response.ok) {
    await throwApiError(response);
  }
  const user = (await response.json()) as AuthUser;
  return configureAuthRuntime({
    apiToken: getStoredApiToken(),
    adminToken: user.is_admin ? getStoredApiToken() : getStoredAdminToken(),
    userEmail: user.email,
    isAdmin: user.is_admin,
  });
}

export async function fetchVoices(locale?: string, engine?: TtsEngine, model?: string): Promise<VoicesResponse> {
  const params = new URLSearchParams();
  if (locale) {
    params.set("locale", locale);
  }
  if (engine) {
    params.set("engine", engine);
  }
  if (model) {
    params.set("model", model);
  }
  const query = params.toString();
  return cachedGetJson<VoicesResponse>(`${API_BASE_URL}/api/tts/voices${query ? `?${query}` : ""}`);
}

export type ExtractPdfResponse = {
  filename: string;
  page_count: number;
  text: string;
};

export async function extractPdfText(file: File): Promise<ExtractPdfResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await apiFetch(`${API_BASE_URL}/api/tts/extract-pdf`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export type PolishPdfTextResponse = {
  provider: string;
  model: string | null;
  polished_text: string;
};

export async function polishPdfText(text: string, provider?: string, model?: string): Promise<PolishPdfTextResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/tts/polish-pdf-text`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text, provider, model }),
  });

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}


export function buildSpeakUrl(params: {
  text: string;
  voice?: string;
  voiceB?: string;
  rate?: string;
  engine?: TtsEngine;
  engineB?: TtsEngine;
  model?: string;
  modelB?: string;
}): string {
  const url = new URL(`${API_BASE_URL}/api/tts/speak`);
  url.searchParams.set("text", params.text);
  if (params.voice) {
    url.searchParams.set("voice", params.voice);
  }
  if (params.voiceB) {
    url.searchParams.set("voice_b", params.voiceB);
  }
  if (params.rate) {
    url.searchParams.set("rate", params.rate);
  }
  if (params.engine) {
    url.searchParams.set("engine", params.engine);
  }
  if (params.engineB) {
    url.searchParams.set("engine_b", params.engineB);
  }
  if (params.model) {
    url.searchParams.set("model", params.model);
  }
  if (params.modelB) {
    url.searchParams.set("model_b", params.modelB);
  }
  return url.toString();
}

type ParsedError = {
  message: string;
  detail?: ApiErrorDetail;
};

function parseDetail(value: unknown): ApiErrorDetail | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const obj = value as Record<string, unknown>;
  const code = typeof obj.code === "string" ? obj.code : undefined;
  const message = typeof obj.message === "string" ? obj.message : undefined;
  const meta =
    obj.meta && typeof obj.meta === "object"
      ? (obj.meta as Record<string, unknown>)
      : undefined;
  if (!code && !message && !meta) {
    return undefined;
  }
  return { code, message, meta };
}

function detailToMessage(detail: ApiErrorDetail): string {
  const code = (detail.code || "").trim();
  const message = (detail.message || "").trim();
  if (code && message) {
    return `${code}: ${message}`;
  }
  if (message) {
    return message;
  }
  if (code) {
    return code;
  }
  return "Request failed.";
}

async function parseError(response: Response): Promise<ParsedError> {
  try {
    const data = (await response.json()) as unknown;
    if (data && typeof data === "object") {
      const dataObj = data as Record<string, unknown>;
      if (typeof dataObj.detail === "string") {
        return { message: dataObj.detail };
      }
      const detail = parseDetail(dataObj.detail);
      if (detail) {
        return { message: detailToMessage(detail), detail };
      }
      const directDetail = parseDetail(dataObj);
      if (directDetail) {
        return { message: detailToMessage(directDetail), detail: directDetail };
      }
    }
  } catch {
    // ignore parse failure
  }
  return { message: `Request failed: ${response.status}` };
}

async function throwApiError(response: Response): Promise<never> {
  const parsed = await parseError(response);
  throw new ApiRequestError(parsed.message, response.status, parsed.detail);
}

export async function fetchSpeakAudio(params: {
  text: string;
  voice?: string;
  voiceB?: string;
  rate?: string;
  engine?: TtsEngine;
  engineB?: TtsEngine;
  model?: string;
  modelB?: string;
}): Promise<TtsAudioResponse> {
  const url = buildSpeakUrl(params);
  const response = await apiFetch(url, {
    headers: buildEverMemHeaders(true, "tts")
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return {
    blob: await response.blob(),
    memorySaved: response.headers.get("X-EverMem-Saved") === "true",
    voice: response.headers.get("X-TTS-Voice") || undefined,
    engine: response.headers.get("X-TTS-Engine") || undefined,
  };
}

export async function createChatCompletion(
  payload: ChatRequest
): Promise<ChatResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

function parseSseBlock(block: string): { event: string; data: string } | null {
  const lines = block.split("\n");
  let eventName = "message";
  const dataLines: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line) {
      continue;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim() || "message";
      continue;
    }
    if (line.startsWith("data:")) {
      const rawData = line.slice(5);
      dataLines.push(rawData.startsWith(" ") ? rawData.slice(1) : rawData);
    }
  }

  if (!dataLines.length) {
    return null;
  }
  return { event: eventName, data: dataLines.join("\n") };
}

function handleSseChunk(chunk: string, handlers: StreamEventHandlers): boolean {
  const parsed = parseSseBlock(chunk);
  if (!parsed) {
    return false;
  }

  // SSE events are self-contained: one malformed event (truncated chunk at a
  // proxy boundary, stray keep-alive comment) must not kill the whole chat
  // stream — skip it and keep reading.
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(parsed.data) as Record<string, unknown>;
  } catch {
    return false;
  }
  if (parsed.event === "delta") {
    const content = payload.content;
    if (typeof content === "string" && content.length > 0) {
      handlers.onDelta(content);
    }
    return false;
  }
  if (parsed.event === "reasoning") {
    const content = payload.content;
    if (typeof content === "string" && content.length > 0) {
      handlers.onReasoning?.(content);
    }
    return false;
  }
  if (parsed.event === "done") {
    const meta = {
      memoriesRetrieved: typeof payload.memories_retrieved === "number" ? payload.memories_retrieved : 0,
      memorySaved: typeof payload.memory_saved === "boolean" ? payload.memory_saved : false
    };
    handlers.onDone?.(meta);
    return true;
  }
  if (parsed.event === "error") {
    const detail =
      typeof payload.detail === "string" ? payload.detail : "Chat stream failed.";
    throw new Error(detail);
  }
  return false;
}

export async function streamChatCompletion(
  payload: ChatRequest,
  handlers: StreamEventHandlers,
  options: { memoryGroupId?: string; signal?: AbortSignal } = {}
): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/chat/completions/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...buildEverMemHeaders(
        true,
        "chat",
        options.memoryGroupId ? { groupId: options.memoryGroupId } : {}
      )
    },
    body: JSON.stringify(payload),
    signal: options.signal
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  if (!response.body) {
    throw new Error("Chat stream is unavailable: empty response body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const isDone = handleSseChunk(block, handlers);
      if (isDone) {
        return;
      }
    }
  }

  const finalChunk = buffer.trim();
  if (finalChunk) {
    handleSseChunk(finalChunk, handlers);
  }
  handlers.onDone?.();
}

export async function translateText(
  payload: TranslateRequest
): Promise<TranslateResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/translate/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function translateImage(params: {
  image_file: File;
  target_language: string;
  source_language?: string;
  provider?: string;
  model?: string;
}): Promise<TranslateResponse> {
  const formData = new FormData();
  formData.append("image_file", params.image_file);
  formData.append("target_language", params.target_language);
  formData.append("source_language", params.source_language || "auto");
  formData.append("provider", params.provider || "DashScope");
  if (params.model) {
    formData.append("model", params.model);
  }

  const response = await apiFetch(`${API_BASE_URL}/api/translate/image`, {
    method: "POST",
    body: formData
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function listCustomVoices(
  voiceType: VoiceType,
  provider?: string
): Promise<CustomVoiceListResponse> {
  let url = `${API_BASE_URL}/api/voices/?voice_type=${encodeURIComponent(voiceType)}`;
  if (provider) {
    url += `&provider=${encodeURIComponent(provider)}`;
  }
  return cachedGetJson<CustomVoiceListResponse>(url);
}

export async function createVoiceDesign(
  payload: VoiceDesignRequest
): Promise<VoiceCreateResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/voices/design`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function createVoiceClone(params: {
  preferred_name: string;
  audio_file: File;
  provider?: string;
}): Promise<VoiceCreateResponse> {
  const formData = new FormData();
  formData.append("preferred_name", params.preferred_name);
  formData.append("audio_file", params.audio_file);
  if (params.provider) {
    formData.append("provider", params.provider);
  }

  const response = await apiFetch(`${API_BASE_URL}/api/voices/clone`, {
    method: "POST",
    body: formData
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function deleteCustomVoice(
  voiceName: string,
  voiceType: VoiceType,
  provider?: string
): Promise<void> {
  let url = `${API_BASE_URL}/api/voices/${encodeURIComponent(voiceName)}?voice_type=${encodeURIComponent(voiceType)}`;
  if (provider) {
    url += `&provider=${encodeURIComponent(provider)}`;
  }
  const response = await apiFetch(url, { method: "DELETE" });
  if (!response.ok) {
    await throwApiError(response);
  }
}

export async function fetchSettings(): Promise<SettingsResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/settings/`);
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function fetchDesktopStatus(): Promise<DesktopStatusResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/settings/desktop-status`);
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function updateSettings(
  settingsPatch: Record<string, unknown>,
  merge: boolean = true
): Promise<SettingsResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merge,
        settings: settingsPatch
      })
    },
    { useAdminToken: true }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export type FetchModelsResponse = {
  provider: string;
  models: string[];
  tts_models?: string[];
};

/**
 * Fetch the real credential behind a MASKED_SECRET placeholder for the
 * settings UI eye-toggle. Backend rejects non-secret fields with 404.
 */
export async function revealSettingsSecret(
  section?: string,
  key?: string,
  providerId?: string
): Promise<string> {
  const response = await apiFetch(`${API_BASE_URL}/api/settings/reveal-secret`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      section: section || "",
      key: key || "",
      provider_id: providerId || "",
    }),
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  const data = (await response.json()) as { value: string };
  return data.value;
}

export async function fetchProviderModels(
  provider: string,
  apiKey?: string,
  apiUrl?: string
): Promise<FetchModelsResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/settings/providers/${encodeURIComponent(provider)}/fetch-models`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKey || null,
        base_url: apiUrl || null,
      }),
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function listAudioOverviewPodcasts(
  limit: number = 20
): Promise<AudioOverviewPodcastListResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-overview/podcasts?limit=${encodeURIComponent(String(limit))}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function getLatestAudioOverviewPodcast(): Promise<AudioOverviewPodcast> {
  const response = await apiFetch(`${API_BASE_URL}/api/audio-overview/podcasts/latest`);
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function getAudioOverviewPodcast(
  podcastId: number
): Promise<AudioOverviewPodcast> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-overview/podcasts/${encodeURIComponent(String(podcastId))}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function createAudioOverviewPodcast(payload: {
  topic: string;
  language?: string;
  audio_path?: string | null;
  script_lines?: AudioOverviewScriptLine[];
}): Promise<AudioOverviewPodcast> {
  const response = await apiFetch(`${API_BASE_URL}/api/audio-overview/podcasts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function updateAudioOverviewPodcast(
  podcastId: number,
  payload: {
    topic?: string;
    language?: string;
    audio_path?: string | null;
    script_lines?: AudioOverviewScriptLine[];
  }
): Promise<AudioOverviewPodcast> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-overview/podcasts/${encodeURIComponent(String(podcastId))}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function transcribeAudio(file: File, provider?: string): Promise<TranscriptionResponse> {
  const formData = new FormData();
  formData.append("file", file);

  let url = `${API_BASE_URL}/api/transcription/`;
  if (provider) {
    url += `?provider=${encodeURIComponent(provider)}`;
  }

  const response = await apiFetch(url, {
    method: "POST",
    headers: buildEverMemHeaders(true, "transcription"),
    body: formData,
  });

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function createTranscriptionJob(
  file: File,
  provider?: string
): Promise<TranscriptionJobResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (provider) {
    formData.append("provider", provider);
  }

  const response = await apiFetch(`${API_BASE_URL}/api/transcription/jobs`, {
    method: "POST",
    headers: buildEverMemHeaders(true, "transcription"),
    body: formData,
  });

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function createTranscriptionJobFromUrl(fileUrl: string, provider?: string): Promise<TranscriptionJobResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/transcription/jobs/from-url`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildEverMemHeaders(true, "transcription")
    },
    body: JSON.stringify({ file_url: fileUrl, ...(provider ? { provider } : {}) }),
  });

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function listTranscriptionJobs(
  options: { statuses?: string[]; limit?: number } = {}
): Promise<TranscriptionJobListResponse> {
  const search = new URLSearchParams();
  if (options.statuses && options.statuses.length > 0) {
    search.set("status", options.statuses.join(","));
  }
  if (typeof options.limit === "number") {
    search.set("limit", String(options.limit));
  }

  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs${search.toString() ? `?${search.toString()}` : ""}`
  );

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function fetchTranscriptionJob(
  jobId: string,
  options: { refresh?: boolean } = {}
): Promise<TranscriptionJobResponse> {
  const refresh = options.refresh !== false;
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}?refresh=${refresh ? "true" : "false"}`,
    {
      headers: buildEverMemHeaders(true, "transcription")
    }
  );

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function retryTranscriptionJob(jobId: string): Promise<TranscriptionJobResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}/retry`,
    {
      method: "POST",
      headers: buildEverMemHeaders(true, "transcription")
    }
  );

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function deleteTranscriptionJob(jobId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}`,
    {
      method: "DELETE",
      headers: buildEverMemHeaders(true, "transcription")
    }
  );

  if (!response.ok) {
    await throwApiError(response);
  }
}

export async function renameTranscriptionJob(
  jobId: string,
  fileName: string
): Promise<TranscriptionJobResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...buildEverMemHeaders(true, "transcription"),
      },
      body: JSON.stringify({ file_name: fileName }),
    }
  );

  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export function buildRealtimeTranscriptionWebSocketUrl(): string {
  const httpUrl = new URL(API_BASE_URL);
  const protocol = httpUrl.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = new URL(`${protocol}//${httpUrl.host}/api/transcription/realtime`);
  const wsToken = getRealtimeWebSocketToken();
  if (wsToken) {
    wsUrl.searchParams.set("token", wsToken);
  }
  return wsUrl.toString();
}

export async function saveTranscriptionText(
  transcript: string,
  fileName?: string,
  words?: WordTimestamp[] | null
): Promise<TranscriptionJobResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/transcription/jobs/save-text`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildEverMemHeaders(true, "transcription"),
    },
    body: JSON.stringify({ transcript, file_name: fileName, words: words || [] }),
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function getTranscriptionJobWords(jobId: string): Promise<WordTimestamp[]> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}/words`,
    {
      headers: buildEverMemHeaders(true, "transcription"),
    }
  );
  if (response.status === 404) {
    // No word-level timestamps stored (e.g. a MiMo job or a legacy realtime job).
    return [];
  }
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function batchDeleteTranscriptionJobs(
  jobIds: string[]
): Promise<TranscriptionBatchDeleteResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/transcription/jobs/batch-delete`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildEverMemHeaders(true, "transcription"),
    },
    body: JSON.stringify({ job_ids: jobIds }),
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function translateTranscriptionCues(
  jobId: string,
  targetLanguage: string,
  cues?: SubtitleCueItem[],
  provider?: string,
  model?: string
): Promise<TranslateJobResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}/translate`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...buildEverMemHeaders(true, "transcription"),
      },
      body: JSON.stringify({
        target_language: targetLanguage,
        provider,
        model,
        cues: cues || [],
      }),
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function fetchTranscriptionTranslation(
  jobId: string
): Promise<TranslateJobResponse | null> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}/translation`,
    {
      headers: buildEverMemHeaders(true, "transcription"),
    }
  );
  if (!response.ok) {
    return null;
  }
  return response.json();
}

export async function burnTranscriptionVideo(
  jobId: string,
  srtContent: string,
  targetLanguage?: string,
  bilingual: boolean = true
): Promise<BurnVideoResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}/burn-video`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...buildEverMemHeaders(true, "transcription"),
      },
      body: JSON.stringify({
        srt_content: srtContent,
        target_language: targetLanguage,
        bilingual,
      }),
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function saveTranscriptionJobMemory(
  jobId: string
): Promise<TranscriptionJobResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/transcription/jobs/${encodeURIComponent(jobId)}/save-memory`,
    {
      method: "POST",
      // forceScene: an explicit user action should not be vetoed by the
      // "remember recordings" auto-save toggle.
      headers: buildEverMemHeaders(true, "transcription", { forceScene: true }),
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function saveAudioOverviewScript(
  podcastId: number,
  scriptLines: AudioOverviewScriptLine[]
): Promise<AudioOverviewPodcast> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-overview/podcasts/${encodeURIComponent(String(podcastId))}/script`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script_lines: scriptLines })
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function deleteAudioOverviewPodcast(podcastId: number): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-overview/podcasts/${encodeURIComponent(String(podcastId))}`,
    {
      method: "DELETE"
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
}

export async function generateAudioOverviewScript(
  payload: AudioOverviewScriptGenerateRequest,
  options: { useMemory?: boolean } = {}
): Promise<AudioOverviewScriptGenerateResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/audio-overview/scripts/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildEverMemHeaders(options.useMemory ?? true, "podcast")
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function synthesizeAudioOverviewPodcast(
  podcastId: number,
  payload: AudioOverviewSynthesizeRequest
): Promise<AudioOverviewSynthesizeResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-overview/podcasts/${encodeURIComponent(String(podcastId))}/synthesize`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function fetchAudioOverviewPodcastAudio(
  podcastId: number
): Promise<Blob> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-overview/podcasts/${encodeURIComponent(String(podcastId))}/audio`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.blob();
}

export async function createAudioAgentRun(
  payload: AudioAgentCreateRunRequest
): Promise<AudioAgentRunDetail> {
  const response = await apiFetch(`${API_BASE_URL}/api/audio-agent/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildEverMemHeaders(payload.use_memory ?? true, "podcast")
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function listAudioAgentRuns(limit: number = 20): Promise<AudioAgentRunListResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-agent/runs?limit=${encodeURIComponent(String(limit))}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function getAudioAgentRun(runId: number): Promise<AudioAgentRunDetail> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-agent/runs/${encodeURIComponent(String(runId))}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function executeAudioAgentRun(runId: number): Promise<AudioAgentRunDetail> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-agent/runs/${encodeURIComponent(String(runId))}/execute`,
    {
      method: "POST",
      headers: buildEverMemHeaders(true, "podcast")
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function cancelAudioAgentRun(runId: number): Promise<AudioAgentRunDetail> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-agent/runs/${encodeURIComponent(String(runId))}/cancel`,
    { method: "POST" }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function retryAudioAgentRun(runId: number): Promise<AudioAgentRunDetail> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-agent/runs/${encodeURIComponent(String(runId))}/retry`,
    {
      method: "POST",
      headers: buildEverMemHeaders(true, "podcast")
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function listAudioAgentRunEvents(
  runId: number,
  limit: number = 200
): Promise<AudioAgentEventListResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-agent/runs/${encodeURIComponent(String(runId))}/events?limit=${encodeURIComponent(String(limit))}`
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}

export async function synthesizeAudioAgentRun(
  runId: number,
  payload: AudioAgentSynthesizeRequest
): Promise<AudioAgentRunDetail> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/audio-agent/runs/${encodeURIComponent(String(runId))}/synthesize`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json();
}
