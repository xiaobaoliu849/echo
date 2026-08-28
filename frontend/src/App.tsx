import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  clearAuthRuntime,
  fetchCurrentAuthUser,
  loginAuthUser,
  getAuthRuntimeConfig,
  registerAuthUser,
  type AuthRuntimeConfig,
  type ChatMessage,
} from "./api";
import {
  getDefaultText,
  type ActiveTab
} from "./appConfig";
import AuthDialog from "./components/AuthDialog";
import AppSidebar from "./components/AppSidebar";
const SettingsModal = lazy(() => import("./components/SettingsModal"));
import useChat from "./hooks/useChat";
import useAudioOverview from "./hooks/useAudioOverview";
import useSettings from "./hooks/useSettings";
import useTts from "./hooks/useTts";
import useTranslate from "./hooks/useTranslate";
import useVoiceChat from "./hooks/useVoiceChat";
import useVoiceManagement from "./hooks/useVoiceManagement";
const AudioOverviewPage = lazy(() => import("./pages/AudioOverviewPage"));
const ChatPage = lazy(() => import("./pages/ChatPage"));
const PalPage = lazy(() => import("./pages/PalPage"));
const TranslatePage = lazy(() => import("./pages/TranslatePage"));
const VoiceCenterPage = lazy(() => import("./pages/VoiceCenterPage"));
import { I18nProvider, createInlineTranslator, localizeText, type UiLanguage } from "./i18n";
import { formatErrorMessage } from "./utils/errorFormatting";

type ConversationArchiveEntry = {
  id: string;
  content: string;
  chatMessages: ChatMessage[];
  voiceMessages: ChatMessage[];
  chatGroupId: string;
  voiceGroupId: string;
  updatedAt: number;
};

const CONVERSATION_HISTORY_STORAGE_KEY = "vs_conversation_history";
const MAX_CONVERSATION_HISTORY = 30;

function createLocalArchiveId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function loadConversationHistory(): ConversationArchiveEntry[] {
  try {
    const raw = localStorage.getItem(CONVERSATION_HISTORY_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveConversationHistory(entries: ConversationArchiveEntry[]): void {
  try {
    localStorage.setItem(CONVERSATION_HISTORY_STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Ignore storage failures in browser-restricted contexts.
  }
}

function firstMeaningfulMessage(messages: ChatMessage[]): string {
  const preferred = messages.find((item) => item.role === "user" && item.content.trim());
  if (preferred) {
    return preferred.content.trim();
  }
  const fallback = messages.find((item) => item.content.trim());
  return fallback ? fallback.content.trim() : "";
}

function buildConversationHistoryEntry(params: {
  chatMessages: ChatMessage[];
  voiceMessages: ChatMessage[];
  chatGroupId: string;
  voiceGroupId: string;
  language: UiLanguage;
}): ConversationArchiveEntry | null {
  const chatMessages = Array.isArray(params.chatMessages) ? params.chatMessages : [];
  const voiceMessages = Array.isArray(params.voiceMessages) ? params.voiceMessages : [];
  if (chatMessages.length === 0 && voiceMessages.length === 0) {
    return null;
  }

  const baseText = firstMeaningfulMessage(chatMessages) || firstMeaningfulMessage(voiceMessages);
  const preview = baseText.length > 30
    ? `${baseText.slice(0, 30)}...`
    : baseText || localizeText(params.language, "未命名会话", "Untitled Conversation");
  const isVoiceOnly = chatMessages.length === 0 && voiceMessages.length > 0;
  const label = isVoiceOnly
    ? `${createInlineTranslator(params.language)("[语音]", "[Voice]")} ${preview}`
    : preview;

  return {
    id: createLocalArchiveId(),
    content: label,
    chatMessages: chatMessages.map((item) => ({ ...item })),
    voiceMessages: voiceMessages.map((item) => ({ ...item })),
    chatGroupId: params.chatGroupId.trim(),
    voiceGroupId: params.voiceGroupId.trim(),
    updatedAt: Date.now(),
  };
}

function areMessageListsEqual(left: ChatMessage[], right: ChatMessage[]): boolean {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  if (left.length === 0) return true;
  // Fast path: compare last message (changes most often during streaming)
  // and first message (cheap identity check) before falling back to full compare.
  const lastL = left[left.length - 1];
  const lastR = right[right.length - 1];
  if (lastL.content !== lastR.content || lastL.role !== lastR.role) return false;
  if (left.length === 1) return true;
  const firstL = left[0];
  const firstR = right[0];
  if (firstL.content !== firstR.content || firstL.role !== firstR.role) return false;
  return JSON.stringify(left) === JSON.stringify(right);
}

function areArchiveEntriesEquivalent(
  left: ConversationArchiveEntry | null,
  right: ConversationArchiveEntry | null
): boolean {
  if (!left || !right) {
    return false;
  }
  return (
    left.chatGroupId === right.chatGroupId &&
    left.voiceGroupId === right.voiceGroupId &&
    areMessageListsEqual(left.chatMessages, right.chatMessages) &&
    areMessageListsEqual(left.voiceMessages, right.voiceMessages)
  );
}

function areArchiveEntriesSameConversationContent(
  left: ConversationArchiveEntry | null,
  right: ConversationArchiveEntry | null
): boolean {
  if (!left || !right) {
    return false;
  }
  return (
    areMessageListsEqual(left.chatMessages, right.chatMessages) &&
    areMessageListsEqual(left.voiceMessages, right.voiceMessages)
  );
}

function normalizeConversationHistory(entries: ConversationArchiveEntry[]): ConversationArchiveEntry[] {
  const normalized: ConversationArchiveEntry[] = [];
  for (const entry of entries) {
    const hasDuplicate = normalized.some((item) => (
      item.content === entry.content ||
      areArchiveEntriesEquivalent(item, entry) ||
      areArchiveEntriesSameConversationContent(item, entry)
    ));
    if (!hasDuplicate) {
      normalized.push(entry);
    }
  }
  return normalized.slice(0, MAX_CONVERSATION_HISTORY);
}

function resolveVoiceCenterTab(activeTab: ActiveTab): "tts" | "design" | "clone" | "transcribe" {
  switch (activeTab) {
    case "voice_design":
      return "design";
    case "voice_clone":
      return "clone";
    case "transcription":
      return "transcribe";
    case "tts":
    case "voice_center":
    default:
      return "tts";
  }
}

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("chat");
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [authRuntime, setAuthRuntime] = useState<AuthRuntimeConfig>(() => getAuthRuntimeConfig());
  const [conversationHistory, setConversationHistory] = useState<ConversationArchiveEntry[]>(
    () => normalizeConversationHistory(loadConversationHistory())
  );
  const currentArchiveBaselineRef = useRef<ConversationArchiveEntry | null>(null);
  const isDesktopEmbedded =
    typeof window !== "undefined" &&
    Object.prototype.hasOwnProperty.call(window, "pywebview");
  const settings = useSettings({ formatErrorMessage });
  const uiLanguage = settings.displayLanguage;
  const tts = useTts({
    defaultText: getDefaultText(createInlineTranslator(uiLanguage)),
    formatErrorMessage,
    language: uiLanguage,
  });
  const chat = useChat({
    formatErrorMessage,
    providerOptions: settings.providerOptions,
    providerModelCatalog: settings.providerModelCatalog,
    preferredProvider: settings.settingsProvider,
    language: uiLanguage,
  });
  const voiceChat = useVoiceChat({
    formatErrorMessage,
    providerOptions: settings.providerOptions,
    providerModelCatalog: settings.providerModelCatalog,
    preferredProvider: chat.chatProvider,
    preferredModel: chat.chatModel,
    language: uiLanguage,
  });
  const audioOverview = useAudioOverview({ voices: tts.voices, formatErrorMessage, language: uiLanguage });
  const voiceManagement = useVoiceManagement({
    formatErrorMessage,
    language: uiLanguage,
    dashscopeApiKeyConfigured: settings.dashscopeApiKeyConfigured,
    xiaomiApiKeyConfigured: settings.xiaomiApiKeyConfigured,
  });
  const { errorRuntimeContext } = settings;

  const translate = useTranslate({ formatErrorMessage, language: uiLanguage });
  const workspaceClassName = `vsWorkspaceViewportInner is-${activeTab.replace(/_/g, "-")}`;
  // Tabs that manage their own internal scrolling and need a fixed-height
  // split layout.  Flagged on the ancestors directly: expressing this as
  // `.vsMainScrollArea:has(.is-transcription)` forced the browser to re-match
  // against every descendant on each DOM mutation, which froze the main
  // thread once the transcription cue list grew to thousands of rows.
  const selfScrollingTab =
    activeTab === "transcription" ||
    activeTab === "voice_center" ||
    activeTab === "pal";
  const normalizedConversationHistory = useMemo(
    () => normalizeConversationHistory(conversationHistory),
    [conversationHistory],
  );
  const shouldShowVoiceCenter =
    activeTab === "voice_center" ||
    activeTab === "tts" ||
    activeTab === "voice_design" ||
    activeTab === "voice_clone" ||
    activeTab === "transcription";
  const authReady = Boolean(
    authRuntime.apiToken ||
    authRuntime.adminToken ||
    authRuntime.hasEnvApiToken ||
    authRuntime.hasEnvAdminToken
  );
  const authLabel = authRuntime.userEmail
    ? authRuntime.userEmail
    : authReady
      ? createInlineTranslator(uiLanguage)("已连接", "Connected")
      : createInlineTranslator(uiLanguage)("登录账号", "Login");

  useEffect(() => {
    if (!authRuntime.apiToken || authRuntime.userEmail) {
      return;
    }
    let disposed = false;
    void fetchCurrentAuthUser()
      .then((next) => {
        if (!disposed) {
          setAuthRuntime(next);
        }
      })
      .catch(() => {
        if (!disposed) {
          setAuthRuntime(clearAuthRuntime());
        }
      });
    return () => {
      disposed = true;
    };
  }, [authRuntime.apiToken, authRuntime.userEmail]);

  function pushConversationHistory(entry: ConversationArchiveEntry | null) {
    if (!entry) {
      return;
    }
    setConversationHistory((prev) => {
      const baseline = currentArchiveBaselineRef.current;
      if (baseline && areArchiveEntriesEquivalent(entry, baseline)) {
        return prev;
      }
      const duplicate = prev.find((item) => (
        areArchiveEntriesEquivalent(item, entry) ||
        areArchiveEntriesSameConversationContent(item, entry) ||
        item.content === entry.content
      ));
      const nextEntry = baseline
        ? { ...entry, id: baseline.id }
        : duplicate
          ? { ...entry, id: duplicate.id }
          : entry;
      const filtered = prev.filter((item) => (
        item.id !== nextEntry.id &&
        !areArchiveEntriesEquivalent(item, nextEntry) &&
        !areArchiveEntriesSameConversationContent(item, nextEntry) &&
        item.content !== nextEntry.content
      ));
      const next = normalizeConversationHistory([nextEntry, ...filtered]);
      saveConversationHistory(next);
      currentArchiveBaselineRef.current = nextEntry;
      return next;
    });
  }

  function archiveActiveConversation() {
    pushConversationHistory(
      buildConversationHistoryEntry({
        chatMessages: chat.chatMessages,
        voiceMessages: voiceChat.voiceChatArchiveMessages,
        chatGroupId: chat.chatMemoryGroupId,
        voiceGroupId: voiceChat.voiceChatMemoryGroupId,
        language: uiLanguage,
      })
    );
  }

  const archiveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    // Debounce archiving to avoid per-delta localStorage writes during streaming.
    if (archiveTimerRef.current) clearTimeout(archiveTimerRef.current);
    archiveTimerRef.current = setTimeout(() => {
      archiveTimerRef.current = null;
      archiveActiveConversation();
    }, 500);
    return () => {
      if (archiveTimerRef.current) clearTimeout(archiveTimerRef.current);
    };
  }, [
    chat.chatMessages,
    voiceChat.voiceChatArchiveMessages,
    chat.chatMemoryGroupId,
    voiceChat.voiceChatMemoryGroupId,
    uiLanguage,
  ]);

  function handleNewChatSession() {
    archiveActiveConversation();
    currentArchiveBaselineRef.current = null;
    chat.onNewSession();
    voiceChat.onResetSession();
    setActiveTab("chat");
  }

  function handleHistorySelect(id: string) {
    const target = normalizedConversationHistory.find((item) => item.id === id);
    if (!target) {
      return;
    }
    const sameAsCurrent =
      target.chatGroupId === chat.chatMemoryGroupId &&
      target.voiceGroupId === voiceChat.voiceChatMemoryGroupId &&
      areMessageListsEqual(target.chatMessages, chat.chatMessages) &&
      areMessageListsEqual(target.voiceMessages, voiceChat.voiceChatMessages);
    if (!sameAsCurrent) {
      archiveActiveConversation();
    }
    currentArchiveBaselineRef.current = target;
    setActiveTab("chat");
    chat.replaceSession(target.chatMessages, target.chatGroupId);
    voiceChat.replaceSession(target.voiceMessages, target.voiceGroupId);
  }
  function handleDeleteConversationHistoryItem(id: string) {
    setConversationHistory((prev) => {
      const next = prev.filter((item) => item.id !== id);
      saveConversationHistory(next);
      return next;
    });
  }

  function handleRenameConversationHistoryItem(id: string, newName: string) {
    setConversationHistory((prev) => {
      const next = prev.map((item) => item.id === id ? { ...item, content: newName } : item);
      saveConversationHistory(next);
      return next;
    });
  }

  async function handleAuthLogin(email: string, password: string) {
    setAuthRuntime(await loginAuthUser(email, password));
  }

  async function handleAuthRegister(email: string, password: string) {
    setAuthRuntime(await registerAuthUser(email, password));
  }

  function handleAuthLogout() {
    setAuthRuntime(clearAuthRuntime());
  }

  /* Stable callbacks for memoized AppSidebar */
  const sidebarHandlersRef = useRef({ handleNewChatSession, handleHistorySelect, handleDeleteConversationHistoryItem, handleRenameConversationHistoryItem });
  sidebarHandlersRef.current = { handleNewChatSession, handleHistorySelect, handleDeleteConversationHistoryItem, handleRenameConversationHistoryItem };
  const stableNewChatSession = useCallback(() => sidebarHandlersRef.current.handleNewChatSession(), []);
  const stableHistorySelect = useCallback((id: string) => sidebarHandlersRef.current.handleHistorySelect(id), []);
  const stableDeleteHistoryItem = useCallback((id: string) => sidebarHandlersRef.current.handleDeleteConversationHistoryItem(id), []);
  const stableRenameHistoryItem = useCallback((id: string, newName: string) => sidebarHandlersRef.current.handleRenameConversationHistoryItem(id, newName), []);
  const stableAuthClick = useCallback(() => setAuthDialogOpen(true), []);
  const stableOpenSettings = useCallback(() => setIsSettingsOpen(true), []);

  const sidebarHistoryItems = useMemo(
    () => normalizedConversationHistory.map((item) => ({ id: item.id, content: item.content })),
    [normalizedConversationHistory],
  );

  return (
    <I18nProvider language={uiLanguage}>
      <main className={isDesktopEmbedded ? "vsApp desktopEmbedded" : "vsApp"}>
        <AppSidebar
          activeTab={activeTab}
          authLabel={authLabel}
          authReady={authReady}
          chatHistoryItems={sidebarHistoryItems}
          onAuthClick={stableAuthClick}
          onTabChange={setActiveTab}
          onNewChatSession={stableNewChatSession}
          onHistorySelect={stableHistorySelect}
          onDeleteHistoryItem={stableDeleteHistoryItem}
          onRenameHistoryItem={stableRenameHistoryItem}
          onOpenSettings={stableOpenSettings}
          isSettingsOpen={isSettingsOpen}
        />

        <section className={`vsMainScrollArea${selfScrollingTab ? " is-self-scrolling" : ""}`}>
          <div className={`vsContentMaxContainer${selfScrollingTab ? " is-self-scrolling" : ""}`}>
            <div className="vsWorkspaceViewport">
              <div className={workspaceClassName}>
                <Suspense fallback={<div className="vsPageLoading" />}>
                {activeTab === "chat" ? (
                  <ChatPage
                    chat={chat}
                    voiceChat={voiceChat}
                    settings={settings}
                    errorRuntimeContext={errorRuntimeContext}
                    onOpenSettings={() => setIsSettingsOpen(true)}
                    onOpenPal={() => setActiveTab("pal")}
                  />
                ) : null}

                {shouldShowVoiceCenter ? (
                  <VoiceCenterPage
                    initialSubTab={resolveVoiceCenterTab(activeTab)}
                    tts={tts}
                    design={voiceManagement.design}
                    clone={voiceManagement.clone}
                    errorRuntimeContext={errorRuntimeContext}
                    onSendToChat={(text) => {
                      chat.injectMessage("assistant", text);
                      setActiveTab("chat");
                    }}
                    voiceProvider={voiceManagement.voiceProvider}
                    onVoiceProviderChange={voiceManagement.setVoiceProvider}
                  />
                ) : null}

                {activeTab === "translate" ? (
                  <TranslatePage translate={translate} errorRuntimeContext={errorRuntimeContext} />
                ) : null}

                {activeTab === "audio_overview" ? (
                  <AudioOverviewPage audioOverview={audioOverview} errorRuntimeContext={errorRuntimeContext} />
                ) : null}

                {activeTab === "pal" ? (
                  <PalPage
                    formatErrorMessage={formatErrorMessage}
                    errorRuntimeContext={errorRuntimeContext}
                  />
                ) : null}
                </Suspense>
              </div>
            </div>
          </div>
        </section>
      </main>
      <Suspense fallback={null}>
        <SettingsModal
          open={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          settings={settings}
          errorRuntimeContext={errorRuntimeContext}
        />
      </Suspense>
      <AuthDialog
        open={authDialogOpen}
        auth={authRuntime}
        onClose={() => setAuthDialogOpen(false)}
        onLogin={handleAuthLogin}
        onRegister={handleAuthRegister}
        onLogout={handleAuthLogout}
      />
    </I18nProvider>
  );
}
