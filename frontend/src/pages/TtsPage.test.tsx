import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, it, expect, vi } from 'vitest';
import TtsPage from './TtsPage';
import { createTtsController } from '../test/factories';

describe('TtsPage', () => {
    afterEach(() => {
        vi.restoreAllMocks();
        delete (window as any).pywebview;
    });

    it('renders workstation layout', () => {
        render(
            <TtsPage
                tts={createTtsController()}
                errorRuntimeContext={{}}
            />
        );
        expect(screen.getByText('文本转语音')).toBeInTheDocument();
        expect(screen.getByText('TTS 引擎:')).toBeInTheDocument();
        expect(screen.getByText('完成输入后，点击右下角“生成音频”开始试听')).toBeInTheDocument();
        expect(screen.getByText('生成音频')).toBeInTheDocument();
        expect(screen.getByText('Qwen TTS (阿里云)')).toBeInTheDocument();
    });

    it('renders voice selector', () => {
        render(
            <TtsPage
                tts={createTtsController()}
                errorRuntimeContext={{}}
            />
        );
        expect(screen.getByText('Xiaoxiao (zh-CN)')).toBeInTheDocument();
    });

    it('renders text content in textarea', () => {
        render(
            <TtsPage
                tts={createTtsController({ text: 'Sample test text' })}
                errorRuntimeContext={{}}
            />
        );
        expect(screen.getByDisplayValue('Sample test text')).toBeInTheDocument();
    });

    it('shows placeholder when no audio', () => {
        render(
            <TtsPage
                tts={createTtsController({ audioUrl: '' })}
                errorRuntimeContext={{}}
            />
        );
        expect(screen.getByText('完成输入后，点击右下角“生成音频”开始试听')).toBeInTheDocument();
    });

    it('renders synthesis errors in a full-width notice outside the toolbar', () => {
        const longError = 'TTS_SPEAK_DEPENDENCY_ERROR: Xiaomi API Key is not configured. (request_id: e9f73aeb9bb04e75b6f5d8efcafefeed)';

        render(
            <TtsPage
                tts={createTtsController({
                    ttsEngine: 'xiaomi',
                    ttsError: longError
                })}
                errorRuntimeContext={{}}
            />
        );

        const alert = screen.getByRole('alert');
        expect(alert).toHaveClass('vsTtsErrorNotice');
        expect(alert).toHaveTextContent('Xiaomi API Key is not configured.');
        expect(screen.getByRole('button', { name: '复制请求 ID' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: '查看详情' })).toBeInTheDocument();
    });

    it('wires submit and parameter controls to the tts controller', () => {
        const tts = createTtsController();

        render(
            <TtsPage
                tts={tts}
                errorRuntimeContext={{}}
            />
        );

        fireEvent.change(screen.getByDisplayValue('Sample test text'), {
            target: { value: 'Updated script' }
        });
        fireEvent.change(screen.getByDisplayValue('+0%'), {
            target: { value: '+10%' }
        });
        const combos = screen.getAllByRole('combobox');
        fireEvent.change(combos[0], {
            target: { value: 'edge' }
        });
        fireEvent.change(combos[1], {
            target: { value: 'zh-CN-XiaoxiaoNeural' }
        });
        fireEvent.click(screen.getByRole('button', { name: '生成音频' }));

        expect(tts.onEngineChange).toHaveBeenCalledWith('edge');
        expect(tts.onTextChange).toHaveBeenCalledWith('Updated script');
        expect(tts.onRateChange).toHaveBeenCalledWith('+10%');
        expect(tts.onVoiceChange).toHaveBeenCalledWith('zh-CN-XiaoxiaoNeural');
        expect(tts.onSubmit).toHaveBeenCalledTimes(1);
        expect(tts.onSubmit).toHaveBeenCalledWith(expect.any(Object));
    });

    it('switches into dialogue mode editor', () => {
        const tts = createTtsController();
        render(
            <TtsPage
                tts={tts}
                errorRuntimeContext={{}}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: '对话转语音' }));
        expect(tts.onTtsModeChange).toHaveBeenCalledWith('dialogue');
    });

    it('downloads generated audio through an anchor element', async () => {
        const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { });

        render(
            <TtsPage
                tts={createTtsController({
                    audioUrl: 'blob:test-url',
                    audioBlob: new Blob(['audio'], { type: 'audio/mpeg' })
                })}
                errorRuntimeContext={{}}
            />
        );

        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: /导出音频/ }));
        });

        await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    });

    it('uses pywebview bridge with the generated audio format', async () => {
        const saveAudio = vi.fn().mockResolvedValue({ ok: true, path: 'D:\\\\voice.wav' });
        (window as any).pywebview = {
            api: {
                save_audio_file: saveAudio
            }
        };
        const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { });

        render(
            <TtsPage
                tts={createTtsController({
                    audioUrl: 'blob:test-url',
                    audioBlob: new Blob(['audio'], { type: 'audio/wav' })
                })}
                errorRuntimeContext={{}}
            />
        );

        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: /导出音频/ }));
        });

        await waitFor(() => expect(saveAudio).toHaveBeenCalledTimes(1));
        expect(saveAudio).toHaveBeenCalledWith(
            expect.objectContaining({
                filename: 'voicespirit_tts.wav',
                mime_type: 'audio/wav',
                data_base64: expect.any(String)
            })
        );
        expect(clickSpy).not.toHaveBeenCalled();
    });
});
