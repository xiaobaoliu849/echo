import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import AudioOverviewPage from './AudioOverviewPage';
import { createAudioOverviewController } from '../test/factories';

describe('AudioOverviewPage', () => {
    it('renders the podcast architecture appropriately', async () => {
        render(
            <AudioOverviewPage
                audioOverview={createAudioOverviewController()}
                errorRuntimeContext={{}}
            />
        );

        // Assertions from header
        expect(await screen.findByText(/播客 #12/)).toBeInTheDocument();

        // Switch to Stage 1 to verify topic step
        fireEvent.click(screen.getByRole('button', { name: /1. 主题与资料/ }));
        expect(await screen.findByDisplayValue('AI 对个人学习习惯的影响')).toBeVisible();
        expect(screen.queryByRole('button', { name: /合成播客/ })).not.toBeInTheDocument();

        // Switch to Stage 2 to verify script editor and synth controls
        fireEvent.click(screen.getByRole('button', { name: /2. 剧本与配音/ }));
        expect(await screen.findByText('第一段内容')).toBeVisible();
        expect(screen.getByDisplayValue('AI 对个人学习习惯的影响')).not.toBeVisible();

        // Assertions from synth bar
        expect(await screen.findByRole('button', { name: /合成/ })).toBeInTheDocument();

        // Click back button to return to library and verify the podcast list
        fireEvent.click(screen.getByTitle('返回列表'));
        expect(await screen.findByText(/播客脚本测试/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: '继续编辑' }));
        expect(screen.getByDisplayValue('第一段内容')).toBeVisible();
    });

    it('starts a new draft at the topic step and prevents an empty audio step', () => {
        const controller = createAudioOverviewController({ audioOverviewPodcastId: null, audioAgentRunId: null, audioOverviewScriptLines: [] });
        render(<AudioOverviewPage audioOverview={controller} errorRuntimeContext={{}} />);
        expect(screen.getByText('Echo 播客')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /新建播客/ }));
        expect(controller.onNewDraft).toHaveBeenCalledOnce();
        expect(screen.getByRole('button', { name: /2. 剧本与配音/ })).toBeDisabled();
        expect(screen.getByRole('button', { name: '生成脚本' })).toBeVisible();
    });

    it('moves to script review when generation completes', () => {
        const draft = createAudioOverviewController({ audioOverviewPodcastId: null, audioAgentRunId: null, audioOverviewScriptLines: [] });
        const { rerender } = render(<AudioOverviewPage audioOverview={draft} errorRuntimeContext={{}} />);
        fireEvent.click(screen.getByRole('button', { name: /新建播客/ }));
        rerender(<AudioOverviewPage audioOverview={createAudioOverviewController()} errorRuntimeContext={{}} />);
        expect(screen.getByRole('button', { name: /2. 剧本与配音/ })).toHaveAttribute('aria-current', 'step');
        expect(screen.getByDisplayValue('第一段内容')).toBeVisible();
    });

    it('keeps retry controls visible after a failed generation', () => {
        render(<AudioOverviewPage audioOverview={createAudioOverviewController({ audioAgentRunId: 7, audioAgentStatus: 'failed', audioAgentCanRetry: true })} errorRuntimeContext={{}} />);
        expect(screen.getByRole('button', { name: '重试' })).toBeVisible();
    });

    it('searches history, refreshes once, and opens the selected run', () => {
        const run = { id: 3, podcast_id: null, topic: 'Neural Interfaces', language: 'en', status: 'queued', current_step: '', provider: 'DashScope', model: '', use_memory: false, input_payload: {}, result_payload: {}, error_code: '', error_message: '', created_at: '2026-09-22T04:08:51Z', updated_at: '', completed_at: '' };
        const controller = createAudioOverviewController({ audioOverviewPodcastId: null, agentRunHistory: [run] });
        render(<AudioOverviewPage audioOverview={controller} errorRuntimeContext={{}} />);
        fireEvent.click(screen.getByRole('button', { name: /生成记录/ }));
        expect(screen.getAllByRole('button', { name: '刷新列表' })).toHaveLength(1);
        fireEvent.click(screen.getByRole('button', { name: '刷新列表' }));
        expect(controller.onLoadAgentRunHistory).toHaveBeenCalledOnce();
        fireEvent.change(screen.getByRole('searchbox', { name: '搜索生成记录' }), { target: { value: 'missing' } });
        expect(screen.getByText('没有匹配的记录')).toBeVisible();
        fireEvent.change(screen.getByRole('searchbox', { name: '搜索生成记录' }), { target: { value: 'Neural' } });
        fireEvent.click(screen.getByRole('button', { name: /Neural Interfaces/ }));
        expect(controller.onOpenAgentRun).toHaveBeenCalledWith(run);
    });

    it('displays error and info messages globally', async () => {
        render(
            <AudioOverviewPage
                audioOverview={createAudioOverviewController({
                    audioOverviewError: 'Test error message',
                    audioOverviewInfo: 'Test info message'
                })}
                errorRuntimeContext={{}}
            />
        );
        expect(await screen.findByText('Test info message')).toBeInTheDocument();
        expect(await screen.findByText('Test error message')).toBeInTheDocument();
    });
});
