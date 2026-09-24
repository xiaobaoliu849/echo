import { renderHook, act, waitFor } from '@testing-library/react';
import { beforeEach, describe, it, expect, vi } from 'vitest';
import useTts from './useTts';
import { createFormatErrorMessageStub } from '../test/factories';
import { fetchSpeakAudio, fetchVoices, extractPdfText, polishPdfText, VOICE_CATALOG_CHANGED_EVENT } from '../api';

vi.mock('../api', () => ({
    VOICE_CATALOG_CHANGED_EVENT: 'echo:voice-catalog-changed',
    fetchVoices: vi.fn().mockResolvedValue({ voices: [] }),
    fetchSpeakAudio: vi.fn(),
    extractPdfText: vi.fn().mockResolvedValue({ filename: 'demo.pdf', page_count: 1, text: '' }),
    polishPdfText: vi.fn().mockResolvedValue({ provider: 'DashScope', model: 'model', polished_text: '' })
}));

describe('useTts', () => {
    beforeEach(() => {
        vi.mocked(fetchVoices).mockReset().mockResolvedValue({ count: 0, voices: [] });
    });

    it('supports switching to dialogue mode', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));

        act(() => {
            result.current.onTtsModeChange('dialogue');
            result.current.onDialogueTextChange('A: 你好\nB: 你好，今天聊什么？');
        });

        expect(result.current.ttsMode).toBe('dialogue');
        expect(result.current.activeSourceText).toContain('A: 你好');
    });

    it('initializes and updates text', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));

        expect(result.current.text).toBe('Initial text');
        expect(result.current.ttsEngine).toBe('edge');

        act(() => {
            result.current.onTextChange('New text');
        });

        expect(result.current.text).toBe('New text');
    });

    it('switches TTS engine and clears stale output state', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));

        act(() => {
            result.current.onEngineChange('qwen_flash');
        });

        expect(result.current.ttsEngine).toBe('qwen_flash');
    });

    it('clears stale voices while provider and model catalogs load', async () => {
        const edgeVoice = { name: 'edge-voice', short_name: 'Edge', locale: 'en-US', gender: 'Female' };
        const cartesiaVoice = { name: 'cartesia-voice', short_name: 'Cartesia', locale: 'en-US', gender: 'Female' };
        const nextVoice = { name: 'next-voice', short_name: 'Next', locale: 'en-US', gender: 'Male' };
        let resolveCartesia!: (value: { count: number; voices: typeof cartesiaVoice[] }) => void;
        let resolveNext!: (value: { count: number; voices: typeof nextVoice[] }) => void;
        const cartesiaRequest = new Promise<{ count: number; voices: typeof cartesiaVoice[] }>((resolve) => { resolveCartesia = resolve; });
        const nextRequest = new Promise<{ count: number; voices: typeof nextVoice[] }>((resolve) => { resolveNext = resolve; });
        vi.mocked(fetchVoices).mockImplementation((_locale, engine, model) => {
            if (engine === 'cartesia') return model === 'sonic-3' ? nextRequest : cartesiaRequest;
            return Promise.resolve({ count: 1, voices: [edgeVoice] });
        });

        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Sample', formatErrorMessage }));
        await waitFor(() => expect(result.current.voice).toBe('edge-voice'));

        act(() => result.current.onEngineChange('cartesia'));
        expect(result.current.loadingVoices).toBe(true);
        expect(result.current.voice).toBe('');
        expect(result.current.voiceOptions).toEqual([]);
        expect(result.current.ttsModel).toBe('sonic-preview');

        await act(async () => resolveCartesia({ count: 1, voices: [cartesiaVoice] }));
        expect(result.current.loadingVoices).toBe(false);
        expect(result.current.voice).toBe('cartesia-voice');

        act(() => result.current.onModelChange('sonic-3'));
        expect(result.current.loadingVoices).toBe(true);
        expect(result.current.voice).toBe('');
        expect(result.current.voiceOptions).toEqual([]);

        await act(async () => resolveNext({ count: 1, voices: [nextVoice] }));
        expect(result.current.loadingVoices).toBe(false);
        expect(result.current.voice).toBe('next-voice');
    });

    it('reloads and exposes a newly created Gemini voice when the voice catalog changes', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));
        const clonedVoice = {
            name: 'voice_xiao_123',
            short_name: 'xiao',
            locale: 'multi',
            gender: 'Custom',
        };

        vi.mocked(fetchVoices).mockResolvedValue({ count: 1, voices: [clonedVoice] });
        await act(async () => {
            window.dispatchEvent(new Event(VOICE_CATALOG_CHANGED_EVENT));
        });

        expect(result.current.voiceOptions).toContainEqual({ value: 'voice_xiao_123', label: 'xiao (自定义)' });
    });

    it('blocks pdf mode submit without prepared text', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));

        act(() => {
            result.current.onTtsModeChange('pdf');
        });

        await act(async () => {
            await result.current.onPdfFileChange(new File(['pdf'], 'demo.pdf', { type: 'application/pdf' }));
        });

        await act(async () => {
            await result.current.onSubmit({ preventDefault() {} } as any);
        });

        expect(result.current.ttsError).toBe('请先选择 PDF 并准备可朗读文本。');
    });

    it('extracts pdf text successfully on file change', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));
        
        const mockExtractedText = "Extracted text content from PDF file.";
        vi.mocked(extractPdfText).mockResolvedValueOnce({
            filename: 'demo.pdf',
            page_count: 3,
            text: mockExtractedText
        });

        act(() => {
            result.current.onTtsModeChange('pdf');
        });

        await act(async () => {
            await result.current.onPdfFileChange(new File(['pdf'], 'demo.pdf', { type: 'application/pdf' }));
        });

        expect(extractPdfText).toHaveBeenCalled();
        expect(result.current.pdfText).toBe(mockExtractedText);
        expect(result.current.ttsInfo).toContain("成功从 PDF 提取了 3 页文本");
    });

    it('submits dialogue text to speech generation', async () => {
        vi.mocked(fetchSpeakAudio).mockResolvedValue({
            blob: new Blob(['audio'], { type: 'audio/mpeg' }),
            memorySaved: false
        });

        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));

        act(() => {
            result.current.onTtsModeChange('dialogue');
            result.current.onDialogueTextChange('A: 你好\\nB: 很高兴见到你');
        });

        await act(async () => {
            await result.current.onSubmit({ preventDefault() {} } as any);
        });

        expect(fetchSpeakAudio).toHaveBeenCalledWith(
            expect.objectContaining({
                text: 'A: 你好\\nB: 很高兴见到你',
                engine: 'edge',
                engineB: 'edge'
            })
        );
    });

    it('polishes pdf text successfully', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useTts({ defaultText: 'Initial text', formatErrorMessage }));

        const mockPolishedText = "Polished text content.";
        vi.mocked(polishPdfText).mockResolvedValueOnce({
            provider: 'DashScope',
            model: 'model',
            polished_text: mockPolishedText
        });

        act(() => {
            result.current.onTtsModeChange('pdf');
            result.current.onPdfTextChange('raw text with page number [1] and math symbol $n \\ge 3$');
        });

        await act(async () => {
            await result.current.onPolishPdfText();
        });

        expect(polishPdfText).toHaveBeenCalled();
        expect(result.current.pdfText).toBe(mockPolishedText);
        expect(result.current.ttsInfo).toContain("AI 朗读优化完成");
    });
});
