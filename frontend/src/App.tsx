import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AUTH_REJECTED_EVENT,
  clearAuthRuntime,
  fetchCurrentAuthUser,
  loginAuthUser,
  getAuthRuntimeConfig,
  logoutAuthSession,
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
import AppUpdateNotice from "./components/AppUpdateNotice";
import { lazyWithRetry } from "./utils/lazyWithRetry";
const SettingsModal = lazyWithRetry(() => import("./components/SettingsModal"));
import useChat from "./hooks/useChat";
import useAudioOverview from "./hooks/useAudioOverview";
import useSettings from "./hooks/useSettings";
import useTts from "./hooks/useTts";
import useVoiceChat from "./hooks/useVoiceChat";
import useVoiceManagement from "./hooks/useVoiceManagement";
const AudioOverviewPage = lazyWithRetry(() => import("./pages/AudioOverviewPage"));
const ChatPage = lazyWithRetry(() => import("./pages/ChatPage"));
const PalPage = lazyWithRetry(() => import("./pages/PalPage"));
const VoiceCenterPage = lazyWithRetry(() => import("./pages/VoiceCenterPage"));
import { I18nProvider, createInlineTranslator } from "./i18n";
import { formatErrorMessage } from "./utils/errorFormatting";
import type { SubtitleItem } from "./hooks/useTavusConversation";

import {
  areArchiveEntriesEquivalent,
  areArchiveEntriesSameConversationContent,
  areArchiveTitlesDuplicate,
  areMessageListsEqual,
  buildConversationHistoryEntry,
  normalizeConversationHistory,
  preserveConversationArchive,
  type ConversationArchiveEntry,
} from "./utils/conversationHistory";

const CONVERSATION_HISTORY_STORAGE_KEY = "vs_conversation_history";

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
  const [settingsInitialCategory, setSettingsInitialCategory] = useState<"provider" | "desktop">("provider");
  const [authRuntime, setAuthRuntime] = useState<AuthRuntimeConfig>(() => getAuthRuntimeConfig());
  const [conversationHistory, setConversationHistory] = useState<ConversationArchiveEntry[]>(() => {
    // Persist the normalized form once at startup so legacy entries (no kind,
    // title-only video markers) are upgraded in storage; later writes all go
    // through updateConversationHistory, which saves synchronously.
    const loaded = normalizeConversationHistory(loadConversationHistory());
    saveConversationHistory(loaded);
    return loaded;
  });
  const conversationHistoryRef = useRef(conversationHistory);
  const currentArchiveBaselineRef = useRef<ConversationArchiveEntry | null>(null);
  const activeArchiveDeletedRef = useRef(false);
  const archiveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isDesktopEmbedded = typeof window !== "undefined" &&
    (window.isElectron === true || Object.prototype.hasOwnProperty.call(window, "pywebview"));
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
    elevenlabsApiKeyConfigured: settings.elevenlabsApiKeyConfigured,
    googleApiKeyConfigured: settings.googleApiKeyConfigured,
  });
  const { errorRuntimeContext } = settings;

  useEffect(() => {
    const handleOpenSettings = (e: Event) => {
      const customEvent = e as CustomEvent<{ category?: string; provider?: string }>;
      const { provider } = customEvent.detail || {};
      if (provider) {
        settings.onProviderChange(provider);
      }
      setIsSettingsOpen(true);
    };
    window.addEventListener("open-settings", handleOpenSettings);
    return () => window.removeEventListener("open-settings", handleOpenSettings);
  }, [settings]);

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

  // When credentials are rejected, clear stored runtime state but DO NOT force
  // open the login modal to interrupt the user; user can voluntarily click login.
  useEffect(() => {
    function handleAuthRejected() {
      setAuthRuntime(clearAuthRuntime());
    }
    window.addEventListener(AUTH_REJECTED_EVENT, handleAuthRejected);
    return () => window.removeEventListener(AUTH_REJECTED_EVENT, handleAuthRejected);
  }, []);

  function updateConversationHistory(update: (prev: ConversationArchiveEntry[]) => ConversationArchiveEntry[]) {
    // Apply changes synchronously so a queued save cannot adopt a newly selected session.
    const next = update(conversationHistoryRef.current);
    conversationHistoryRef.current = next;
    saveConversationHistory(next);
    setConversationHistory(next);
  }

  function cancelPendingArchive() {
    if (archiveTimerRef.current) {
      clearTimeout(archiveTimerRef.current);
      archiveTimerRef.current = null;
    }
  }

  function pushConversationHistory(entry: ConversationArchiveEntry | null) {
    if (!entry || activeArchiveDeletedRef.current) return;
    const baseline = currentArchiveBaselineRef.current;
    const candidate = preserveConversationArchive(entry, baseline);
    if (baseline && areArchiveEntriesEquivalent(candidate, baseline) && candidate.content === baseline.content) {
      return;
    }
    updateConversationHistory((prev) => {
      const duplicate = prev.find((item) => (
        areArchiveEntriesEquivalent(item, candidate) ||
        areArchiveEntriesSameConversationContent(item, candidate) ||
        areArchiveTitlesDuplicate(item, candidate)
      ));
      const nextEntry = baseline
        ? candidate
        : duplicate
          ? preserveConversationArchive(candidate, duplicate)
          : candidate;
      const filtered = prev.filter((item) => (
        item.id !== nextEntry.id &&
        !areArchiveEntriesEquivalent(item, nextEntry) &&
        !areArchiveEntriesSameConversationContent(item, nextEntry) &&
        !areArchiveTitlesDuplicate(item, nextEntry)
      ));
      currentArchiveBaselineRef.current = nextEntry;
      return normalizeConversationHistory([nextEntry, ...filtered]);
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

  useEffect(() => {
    // Debounce archiving to avoid per-delta localStorage writes during streaming.
    cancelPendingArchive();
    archiveTimerRef.current = setTimeout(() => {
      archiveTimerRef.current = null;
      archiveActiveConversation();
    }, 500);
    return cancelPendingArchive;
  }, [
    chat.chatMessages,
    voiceChat.voiceChatArchiveMessages,
    chat.chatMemoryGroupId,
    voiceChat.voiceChatMemoryGroupId,
    uiLanguage,
  ]);

  function handleNewChatSession() {
    cancelPendingArchive();
    archiveActiveConversation();
    currentArchiveBaselineRef.current = null;
    activeArchiveDeletedRef.current = false;
    chat.onNewSession();
    voiceChat.onResetSession();
    setActiveTab("chat");
  }

  function handleHistorySelect(id: string) {
    const target = conversationHistoryRef.current.find((item) => item.id === id);
    if (!target) {
      return;
    }
    cancelPendingArchive();
    const sameAsCurrent =
      currentArchiveBaselineRef.current?.id === target.id &&
      target.chatGroupId === chat.chatMemoryGroupId &&
      target.voiceGroupId === voiceChat.voiceChatMemoryGroupId &&
      areMessageListsEqual(target.chatMessages, chat.chatMessages) &&
      areMessageListsEqual(target.voiceMessages, voiceChat.voiceChatMessages);
    if (!sameAsCurrent) {
      archiveActiveConversation();
    }
    currentArchiveBaselineRef.current = target;
    activeArchiveDeletedRef.current = false;
    setActiveTab("chat");
    chat.replaceSession(target.chatMessages, target.chatGroupId);
    voiceChat.replaceSession(target.voiceMessages, target.voiceGroupId);
  }
  function handleDeleteConversationHistoryItem(id: string) {
    if (currentArchiveBaselineRef.current?.id === id) {
      cancelPendingArchive();
      activeArchiveDeletedRef.current = true;
    }
    updateConversationHistory((prev) => prev.filter((item) => item.id !== id));
  }

  function handleRenameConversationHistoryItem(id: string, newName: string) {
    if (currentArchiveBaselineRef.current?.id === id) {
      currentArchiveBaselineRef.current = {
        ...currentArchiveBaselineRef.current, content: newName, titleCustomized: true,
      };
    }
    updateConversationHistory((prev) => prev.map((item) => (
      item.id === id ? { ...item, content: newName, titleCustomized: true } : item
    )));
  }

  function handlePalConversationEnded(transcripts: SubtitleItem[], palName: string, conversationId: string) {
    if (!conversationId || transcripts.length === 0) return;
    // Include the trailing non-final turn when the call ends.
    const nonEmpty = transcripts.filter((item) => item.text.trim());
    if (nonEmpty.length === 0) return;
    const voiceMessages: ChatMessage[] = nonEmpty.map((item) => ({
      role: item.speaker === "user" ? "user" : "assistant",
      content: item.text,
    }));
    const prefix = palName
      ? createInlineTranslator(uiLanguage)(`[视频 ${palName}]`, `[Video ${palName}]`)
      : createInlineTranslator(uiLanguage)("[视频PAL]", "[Video PAL]");
    const firstUserText = nonEmpty.find((item) => item.speaker === "user")?.text || nonEmpty[0].text;
    const preview = firstUserText.length > 30 ? `${firstUserText.slice(0, 30)}...` : firstUserText;
    const entry: ConversationArchiveEntry = {
      id: `pal-${conversationId}`,
      content: `${prefix} ${preview}`,
      chatMessages: [],
      voiceMessages,
      chatGroupId: "",
      voiceGroupId: "",
      kind: "video",
      palConversationId: conversationId,
      updatedAt: Date.now(),
    };
    updateConversationHistory((prev) => normalizeConversationHistory([
      entry, ...prev.filter((item) => item.id !== entry.id),
    ]));
  }

  async function handleAuthLogin(email: string, password: string) {
    setAuthRuntime(await loginAuthUser(email, password));
  }

  async function handleAuthRegister(email: string, password: string) {
    setAuthRuntime(await registerAuthUser(email, password));
  }

  function handleAuthLogout() {
    // Captures the token, clears local storage synchronously, then revokes
    // the server-side session in the background so the UI never waits.
    void logoutAuthSession();
    setAuthRuntime(getAuthRuntimeConfig());
  }

  /* Stable callbacks for memoized AppSidebar */
  const sidebarHandlersRef = useRef({ handleNewChatSession, handleHistorySelect, handleDeleteConversationHistoryItem, handleRenameConversationHistoryItem });
  sidebarHandlersRef.current = { handleNewChatSession, handleHistorySelect, handleDeleteConversationHistoryItem, handleRenameConversationHistoryItem };
  const stableNewChatSession = useCallback(() => sidebarHandlersRef.current.handleNewChatSession(), []);
  const stableHistorySelect = useCallback((id: string) => sidebarHandlersRef.current.handleHistorySelect(id), []);
  const stableDeleteHistoryItem = useCallback((id: string) => sidebarHandlersRef.current.handleDeleteConversationHistoryItem(id), []);
  const stableRenameHistoryItem = useCallback((id: string, newName: string) => sidebarHandlersRef.current.handleRenameConversationHistoryItem(id, newName), []);
  const stableAuthClick = useCallback(() => setAuthDialogOpen(true), []);
  const stableOpenSettings = useCallback(() => {
    setSettingsInitialCategory("provider");
    setIsSettingsOpen(true);
  }, []);

  const palConversationEndedRef = useRef(handlePalConversationEnded);
  palConversationEndedRef.current = handlePalConversationEnded;
  const stablePalConversationEnded = useCallback(
    (transcripts: SubtitleItem[], palName: string, conversationId: string) => palConversationEndedRef.current(transcripts, palName, conversationId),
    []
  );

  const sidebarHistoryItems = useMemo(
    () => normalizedConversationHistory.map((item) => ({ id: item.id, content: item.content })),
    [normalizedConversationHistory],
  );

  return (
    <I18nProvider language={uiLanguage}>
      <AppUpdateNotice hidden={isSettingsOpen} onOpenUpdates={() => {
        setSettingsInitialCategory("desktop");
        setIsSettingsOpen(true);
      }} />
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
                    cloneProvider={voiceManagement.cloneProvider}
                    onVoiceProviderChange={voiceManagement.setVoiceProvider}
                    onOpenSettings={(prov) => {
                      if (prov) settings.onProviderChange(prov);
                      setIsSettingsOpen(true);
                    }}
                  />
                ) : null}

                {activeTab === "audio_overview" ? (
                  <AudioOverviewPage audioOverview={audioOverview} errorRuntimeContext={errorRuntimeContext} />
                ) : null}

                {activeTab === "pal" ? (
                  <PalPage
                    formatErrorMessage={formatErrorMessage}
                    errorRuntimeContext={errorRuntimeContext}
                    onConversationEnded={stablePalConversationEnded}
                    onClose={() => setActiveTab("chat")}
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
          initialCategory={settingsInitialCategory}
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
