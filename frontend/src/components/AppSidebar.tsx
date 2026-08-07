import { memo, useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  getSidebarItems,
  type ActiveTab,
  type HistoryItem
} from "../appConfig";
import { useI18n } from "../i18n";
import {
  Bot,
  Languages,
  Volume2,
  Settings2,
  Fingerprint,
  Mic2,
  FileAudio,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  MessageSquarePlus,
  MoreHorizontal,
  Pencil,
  Trash2
} from "lucide-react";

const IconMap: Record<string, React.ElementType> = {
  Bot,
  Languages,
  Volume2,
  Settings2,
  Fingerprint,
  Mic2,
  FileAudio,
  Settings
};

type Props = {
  activeTab: ActiveTab;
  authLabel: string;
  authReady: boolean;
  chatHistoryItems: HistoryItem[];
  onTabChange: (tab: ActiveTab) => void;
  onAuthClick: () => void;
  onNewChatSession: () => void;
  onHistorySelect: (id: string) => void;
  onDeleteHistoryItem: (id: string) => void;
  onRenameHistoryItem?: (id: string, newName: string) => void;
  onOpenSettings: () => void;
  isSettingsOpen?: boolean;
};

function AppSidebar({
  activeTab,
  authLabel,
  authReady,
  chatHistoryItems,
  onTabChange,
  onAuthClick,
  onNewChatSession,
  onHistorySelect,
  onDeleteHistoryItem,
  onRenameHistoryItem,
  onOpenSettings,
  isSettingsOpen = false,
}: Props) {
  const { t } = useI18n();
  const [isCollapsed, setIsCollapsed] = useState(() => {
    const saved = localStorage.getItem("vs_sidebar_collapsed");
    return saved === "true";
  });
  const navigationItems = getSidebarItems(t).filter((item) => item.tab !== "chat");
  const hasHistoryItems = chatHistoryItems.length > 0;
  const isVoiceCenterActive =
    activeTab === "voice_center" ||
    activeTab === "tts" ||
    activeTab === "voice_design" ||
    activeTab === "voice_clone" ||
    activeTab === "transcription";

  // --- Context menu state (ChatGPT-style: hover dots → fixed portal menu) ---
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const moreBtnRef = useRef<HTMLButtonElement | null>(null);
  const editInputRef = useRef<HTMLInputElement>(null);
  const historyListRef = useRef<HTMLDivElement>(null);

  const closeMenu = useCallback(() => {
    setOpenMenuId(null);
    setMenuPos(null);
    moreBtnRef.current = null;
  }, []);

  useEffect(() => {
    localStorage.setItem("vs_sidebar_collapsed", String(isCollapsed));
    if (isCollapsed) closeMenu();
  }, [isCollapsed, closeMenu]);

  // Close floating menu on outside click / Escape / scroll / resize
  useEffect(() => {
    if (!openMenuId) return;

    function handlePointerDown(e: MouseEvent) {
      const target = e.target as Node;
      if (menuRef.current?.contains(target)) return;
      if (moreBtnRef.current?.contains(target)) return;
      closeMenu();
    }

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") closeMenu();
    }

    function handleViewportChange() {
      closeMenu();
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", handleViewportChange);
    // Capture scroll from history list (and any ancestor) so menu doesn't float away
    const listEl = historyListRef.current;
    listEl?.addEventListener("scroll", handleViewportChange, true);
    document.addEventListener("scroll", handleViewportChange, true);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", handleViewportChange);
      listEl?.removeEventListener("scroll", handleViewportChange, true);
      document.removeEventListener("scroll", handleViewportChange, true);
    };
  }, [openMenuId, closeMenu]);

  // Auto-focus rename input when entering edit mode
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const handleMenuToggle = useCallback((e: React.MouseEvent<HTMLButtonElement>, id: string) => {
    e.stopPropagation();
    e.preventDefault();

    if (openMenuId === id) {
      closeMenu();
      return;
    }

    const btn = e.currentTarget;
    const rect = btn.getBoundingClientRect();
    const menuWidth = 168;
    const menuHeight = 96;
    const gap = 6;
    const pad = 8;

    // Prefer below the button; flip above if near bottom edge
    let top = rect.bottom + gap;
    if (top + menuHeight > window.innerHeight - pad) {
      top = Math.max(pad, rect.top - menuHeight - gap);
    }

    // Align menu's right edge with button's right edge (ChatGPT style)
    let left = rect.right - menuWidth;
    if (left < pad) left = pad;
    if (left + menuWidth > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - menuWidth - pad);
    }

    moreBtnRef.current = btn;
    setMenuPos({ top, left });
    setOpenMenuId(id);
  }, [openMenuId, closeMenu]);

  const handleRenameStart = useCallback((item: HistoryItem) => {
    setEditingId(item.id);
    setEditingValue(item.content);
    closeMenu();
  }, [closeMenu]);

  const handleRenameCommit = useCallback(() => {
    if (editingId && editingValue.trim() && onRenameHistoryItem) {
      onRenameHistoryItem(editingId, editingValue.trim());
    }
    setEditingId(null);
    setEditingValue("");
  }, [editingId, editingValue, onRenameHistoryItem]);

  const handleRenameKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleRenameCommit();
    } else if (e.key === "Escape") {
      setEditingId(null);
      setEditingValue("");
    }
  }, [handleRenameCommit]);

  const handleDeleteClick = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    closeMenu();
    onDeleteHistoryItem(id);
  }, [onDeleteHistoryItem, closeMenu]);

  const openMenuItem = openMenuId
    ? chatHistoryItems.find((item) => item.id === openMenuId) ?? null
    : null;

  return (
    <div className={`vsSidebarShell ${isCollapsed ? "collapsed" : ""}`}>
      <aside className={`vsSidebar ${isCollapsed ? "collapsed" : ""}`}>
        <div className="vsSidebarHeader">
          <div className="vsBrand">
            <div className="vsBrandIcon">VS</div>
            <div className="vsBrandCopy">
              <h1>VoiceSpirit</h1>
            </div>
          </div>
          <button
            type="button"
            className="vsSidebarToggleBtn"
            onClick={() => setIsCollapsed(!isCollapsed)}
            aria-label={isCollapsed ? t("展开侧边栏", "Expand sidebar") : t("收起侧边栏", "Collapse sidebar")}
            aria-expanded={!isCollapsed}
            title={isCollapsed ? t("展开侧边栏", "Expand sidebar") : t("收起侧边栏", "Collapse sidebar")}
          >
            {isCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>

        <div className="vsSidebarTop">
          <div className="vsSidebarAction">
            <button
              type="button"
              className="vsNewChatBtn"
              onClick={onNewChatSession}
              title={isCollapsed ? t("新建对话", "New chat") : undefined}
            >
              <span className="vsNewChatIcon">
                <MessageSquarePlus size={18} />
              </span>
              <span className="vsNewChatText">{t("新建对话", "New chat")}</span>
            </button>
          </div>
        </div>

        <div className="vsSidebarBody">
          <div className="vsSidebarNavScroll custom-scrollbar">
            <nav className="vsNav vsSidebarMainNav">
              {navigationItems.map((item) => {
                const IconComponent = IconMap[item.icon];
                return (
                  <button
                    key={item.tab}
                    type="button"
                    className={`vsNavItem ${(item.tab === "voice_center" ? isVoiceCenterActive : activeTab === item.tab) ? "active" : ""}`}
                    onClick={() => onTabChange(item.tab as ActiveTab)}
                    title={isCollapsed ? item.tooltip || item.label : undefined}
                    data-testid={`nav-${item.tab}`}
                  >
                    <span className="vsNavIcon" aria-hidden="true">
                      {IconComponent && <IconComponent size={20} />}
                    </span>
                    <span className="vsNavItemText">{item.label}</span>
                    {(item.tab === "voice_center" ? isVoiceCenterActive : activeTab === item.tab) ? (
                      <div className="vsNavActiveIndicator" />
                    ) : null}
                  </button>
                );
              })}
            </nav>
          </div>

          {hasHistoryItems ? (
            <section className="vsSidebarSection vsHistorySection">
              <div className="vsHistoryList custom-scrollbar" ref={historyListRef}>
                {chatHistoryItems.map((item) => (
                  <div
                    key={item.id}
                    className={`vsHistoryRow ${openMenuId === item.id ? "menu-open" : ""}`}
                  >
                    {editingId === item.id ? (
                      /* --- Inline rename mode --- */
                      <div className="vsHistoryItemEditing">
                        <input
                          ref={editInputRef}
                          type="text"
                          className="vsHistoryEditInput"
                          value={editingValue}
                          onChange={(e) => setEditingValue(e.target.value)}
                          onKeyDown={handleRenameKeyDown}
                          onBlur={handleRenameCommit}
                        />
                      </div>
                    ) : (
                      /* --- Normal display: title full-width, ⋯ floats on hover --- */
                      <>
                        <button
                          type="button"
                          className="vsHistoryItem"
                          onClick={() => {
                            closeMenu();
                            onHistorySelect(item.id);
                          }}
                          title={item.content}
                        >
                          <span className="vsHistoryText">{item.content}</span>
                        </button>
                        <div className="vsHistoryMoreWrapper">
                          <button
                            type="button"
                            className="vsHistoryMoreBtn"
                            data-testid={`history-more-${item.id}`}
                            aria-label={t("更多操作", "More actions")}
                            aria-haspopup="menu"
                            aria-expanded={openMenuId === item.id}
                            onClick={(e) => handleMenuToggle(e, item.id)}
                          >
                            <MoreHorizontal size={16} />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>

        {/* Floating action menu — rendered outside overflow containers (ChatGPT style) */}
        {openMenuItem && menuPos
          ? createPortal(
              <div
                ref={menuRef}
                className="vsHistoryDropdown"
                role="menu"
                style={{ top: menuPos.top, left: menuPos.left }}
              >
                {onRenameHistoryItem ? (
                  <button
                    type="button"
                    role="menuitem"
                    className="vsHistoryDropdownItem"
                    onClick={() => handleRenameStart(openMenuItem)}
                  >
                    <Pencil size={14} />
                    <span>{t("重命名", "Rename")}</span>
                  </button>
                ) : null}
                <button
                  type="button"
                  role="menuitem"
                  className="vsHistoryDropdownItem danger"
                  aria-label={`${t("删除历史", "Delete history")} ${openMenuItem.content}`}
                  onClick={(e) => handleDeleteClick(e, openMenuItem.id)}
                >
                  <Trash2 size={14} />
                  <span>{t("删除", "Delete")}</span>
                </button>
              </div>,
              document.body
            )
          : null}

        <div className="vsSidebarFooter">
          <div className="vsSidebarFooterActions">
            <button
              type="button"
              className="vsVisuallyHidden"
              data-testid="nav-tts"
              aria-label={t("文本到音频", "Text to Audio")}
              onClick={() => onTabChange("tts")}
            />
            <button
              type="button"
              className="vsVisuallyHidden"
              data-testid="nav-voice_design"
              aria-label={t("设计音色", "Voice Design")}
              onClick={() => onTabChange("voice_design")}
            />
            <button
              type="button"
              className="vsVisuallyHidden"
              data-testid="nav-voice_clone"
              aria-label={t("音色克隆", "Voice Clone")}
              onClick={() => onTabChange("voice_clone")}
            />
            <button
              type="button"
              className="vsVisuallyHidden"
              data-testid="nav-transcription"
              aria-label={t("一键转写", "Transcribe")}
              onClick={() => onTabChange("transcription")}
            />
            <button
              type="button"
              className={`vsFooterAction vsLoginBtn ${authReady ? "active" : ""}`}
              title={authReady ? authLabel : t("登录账号", "Login")}
              onClick={onAuthClick}
            >
              <Fingerprint size={18} />
              <span>{authReady ? authLabel : t("登录账号", "Login")}</span>
            </button>

            <button
              type="button"
              className={`vsFooterAction vsSettingsBtn ${isSettingsOpen ? "active" : ""}`}
              data-testid="nav-settings"
              title={t("设置", "Settings")}
              onClick={() => onOpenSettings()}
            >
              <Settings size={18} />
              <span>{t("设置", "Settings")}</span>
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}

export default memo(AppSidebar);
