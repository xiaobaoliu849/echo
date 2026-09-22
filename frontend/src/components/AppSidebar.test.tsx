import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, it, expect, vi } from 'vitest';
import AppSidebar from './AppSidebar';
import type { ActiveTab } from '../appConfig';

const baseProps = {
    activeTab: 'chat' as ActiveTab,
    authLabel: '登录账号',
    authReady: false,
    onAuthClick: vi.fn(),
    onTabChange: vi.fn(),
    onNewChatSession: vi.fn(),
    onHistorySelect: vi.fn(),
    onDeleteHistoryItem: vi.fn(),
    onRenameHistoryItem: vi.fn(),
    onOpenSettings: vi.fn(),
};

describe('AppSidebar', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.clear();
    });

    it('renders simplified navigation without duplicate chat entry', () => {
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[]}
            />
        );
        expect(screen.getByText('Echo')).toBeInTheDocument();
        expect(screen.getByText('新建对话')).toBeInTheDocument();
        expect(screen.queryByText('聊天')).not.toBeInTheDocument();
        expect(screen.queryByText('最近对话')).not.toBeInTheDocument();
    });

    it('shows recent history only when there are chat sessions', () => {
        render(
            <AppSidebar
                {...baseProps}
                activeTab={'translate' as ActiveTab}
                authLabel="demo@example.com"
                authReady={true}
                chatHistoryItems={[{ id: '1', content: '帮我总结今天会议纪要' }]}
            />
        );

        expect(screen.getByText('帮我总结今天会议纪要')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: '更多操作' })).toBeInTheDocument();
    });

    it('keeps the full long title available while CSS truncates its visible text', () => {
        const longTitle = '这是一个非常非常长的历史消息标题，用来验证文字不会把右侧操作按钮挤出侧边栏';
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[{ id: 'long', content: longTitle }]}
            />
        );

        const historyButton = screen.getByRole('button', { name: longTitle });
        expect(historyButton).toHaveAttribute('title', longTitle);
        expect(historyButton.querySelector('.vsHistoryText')).toHaveTextContent(longTitle);
        expect(screen.getByTestId('history-more-long')).toHaveAttribute('aria-expanded', 'false');
    });

    it('opens a floating menu with rename and delete on ⋯ click', () => {
        const onDelete = vi.fn();
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[{ id: '1', content: '帮我总结今天会议纪要' }]}
                onDeleteHistoryItem={onDelete}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: '更多操作' }));

        expect(screen.getByRole('button', { name: '更多操作' })).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByRole('menu')).toBeInTheDocument();
        expect(screen.getByRole('menuitem', { name: '重命名' })).toBeInTheDocument();
        const deleteItem = screen.getByRole('menuitem', { name: /删除历史 帮我总结今天会议纪要/ });
        fireEvent.click(deleteItem);
        expect(onDelete).toHaveBeenCalledWith('1');
    });

    it('renames a history item inline and commits with Enter', () => {
        const onRename = vi.fn();
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[{ id: '1', content: '旧标题' }]}
                onRenameHistoryItem={onRename}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
        fireEvent.click(screen.getByRole('menuitem', { name: '重命名' }));
        const input = screen.getByDisplayValue('旧标题');
        fireEvent.change(input, { target: { value: '新标题' } });
        fireEvent.keyDown(input, { key: 'Enter' });

        expect(onRename).toHaveBeenCalledWith('1', '新标题');
    });

    it('closes the action menu on Escape', () => {
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[{ id: '1', content: '测试标题' }]}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
        expect(screen.getByRole('menu')).toBeInTheDocument();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('does not offer rename when no rename handler is provided', () => {
        render(
            <AppSidebar
                {...baseProps}
                onRenameHistoryItem={undefined}
                chatHistoryItems={[{ id: '1', content: '测试标题' }]}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
        expect(screen.queryByRole('menuitem', { name: '重命名' })).not.toBeInTheDocument();
        expect(screen.getByRole('menuitem', { name: /删除历史 测试标题/ })).toBeInTheDocument();
    });

    it('toggles sidebar collapse state cleanly when clicking the header toggle button', () => {
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[]}
            />
        );

        const toggleBtn = screen.getByRole('button', { name: /收起侧边栏/ });
        expect(toggleBtn).toBeInTheDocument();
        expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');

        fireEvent.click(toggleBtn);

        const expandBtn = screen.getByRole('button', { name: /展开侧边栏/ });
        expect(expandBtn).toBeInTheDocument();
        expect(expandBtn).toHaveAttribute('aria-expanded', 'false');
    });

    it('toggles sidebar collapse state via Ctrl+B shortcut', () => {
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[]}
            />
        );

        const toggleBtn = screen.getByRole('button', { name: /收起侧边栏/ });
        expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');

        fireEvent.keyDown(window, { key: 'b', ctrlKey: true });

        const expandBtn = screen.getByRole('button', { name: /展开侧边栏/ });
        expect(expandBtn).toHaveAttribute('aria-expanded', 'false');

        fireEvent.keyDown(window, { key: 'b', ctrlKey: true });

        expect(screen.getByRole('button', { name: /收起侧边栏/ })).toHaveAttribute('aria-expanded', 'true');
    });

    it('renders the collapsed rail with the logo toggle, and hovering never auto-expands', () => {
        localStorage.setItem('vs_sidebar_collapsed', 'true');
        const { container } = render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[]}
            />
        );

        const aside = container.querySelector('.vsSidebar') as HTMLElement;
        expect(aside).toHaveClass('collapsed');

        const logoToggle = screen.getByRole('button', { name: /展开侧边栏/ });
        expect(logoToggle).toHaveAttribute('aria-expanded', 'false');

        fireEvent.mouseEnter(logoToggle.closest('.vsSidebarHeader') as HTMLElement);
        expect(container.querySelector('.vsSidebar')).toHaveClass('collapsed');
    });

    it('renders unified logo toggle with default mark and hover action icon, without duplicate toggle buttons', () => {
        const { container } = render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[]}
            />
        );

        const header = container.querySelector('.vsSidebarHeader') as HTMLElement;
        const toggleButtons = header.querySelectorAll('.vsSidebarToggleBtn');
        expect(toggleButtons).toHaveLength(1);

        const toggleBtn = toggleButtons[0];
        expect(toggleBtn.querySelector('.vsBrandIconMark')).toBeInTheDocument();
        expect(toggleBtn.querySelector('.vsBrandIconHoverAction')).toBeInTheDocument();
    });

    it('pins the sidebar open when clicking the collapsed logo toggle', () => {
        localStorage.setItem('vs_sidebar_collapsed', 'true');
        const { container } = render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[]}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: /展开侧边栏/ }));

        expect(container.querySelector('.vsSidebar')).not.toHaveClass('collapsed');
        expect(screen.getByRole('button', { name: /收起侧边栏/ })).toHaveAttribute('aria-expanded', 'true');
        expect(localStorage.getItem('vs_sidebar_collapsed')).toBe('false');
    });

    it('starts collapsed on a narrow viewport, then honours an explicit expand', () => {
        const originalWidth = window.innerWidth;
        try {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: 480 });

            const { container } = render(
                <AppSidebar
                    {...baseProps}
                    chatHistoryItems={[]}
                />
            );

            expect(container.querySelector('.vsSidebar')).toHaveClass('collapsed');

            fireEvent.click(screen.getByRole('button', { name: /展开侧边栏/ }));
            expect(container.querySelector('.vsSidebar')).not.toHaveClass('collapsed');

            // A later resize must not undo the user's choice.
            fireEvent(window, new Event('resize'));
            expect(container.querySelector('.vsSidebar')).not.toHaveClass('collapsed');
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth });
        }
    });

    it('restores the rail when the viewport widens, without persisting an automatic collapse', () => {
        const originalWidth = window.innerWidth;
        const setWidth = (value: number) =>
            Object.defineProperty(window, 'innerWidth', { configurable: true, value });
        try {
            setWidth(480);
            const { container } = render(
                <AppSidebar
                    {...baseProps}
                    chatHistoryItems={[]}
                />
            );
            expect(container.querySelector('.vsSidebar')).toHaveClass('collapsed');

            setWidth(1280);
            fireEvent(window, new Event('resize'));
            expect(container.querySelector('.vsSidebar')).not.toHaveClass('collapsed');

            // An automatic collapse must not become the saved preference.
            expect(localStorage.getItem('vs_sidebar_collapsed')).not.toBe('true');
        } finally {
            setWidth(originalWidth);
        }
    });

    it('keeps the test-only navigation anchors out of the tab order and accessibility tree', () => {
        render(
            <AppSidebar
                {...baseProps}
                chatHistoryItems={[]}
            />
        );

        for (const testId of ['nav-tts', 'nav-voice_design', 'nav-voice_clone', 'nav-transcription']) {
            const anchor = screen.getByTestId(testId);
            expect(anchor).toHaveAttribute('tabindex', '-1');
            expect(anchor).toHaveAttribute('aria-hidden', 'true');
        }
        expect(screen.queryByRole('button', { name: '文本到音频' })).not.toBeInTheDocument();
    });
});
