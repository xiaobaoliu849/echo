import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import VoiceClonePage from './VoiceClonePage';
import { createVoiceCloneController } from '../test/factories';

describe('VoiceClonePage', () => {
    it('renders correctly', () => {
        const mockFile = new File(['dummy content'], 'test-audio.mp3', { type: 'audio/mpeg' });

        render(
            <VoiceClonePage
                clone={createVoiceCloneController({
                    cloneName: 'cloned-voice',
                    cloneAudioFile: mockFile
                })}
                errorRuntimeContext={{}}
            />
        );
        
        expect(screen.getByText('暂无克隆的音色')).toBeInTheDocument();
        
        fireEvent.click(screen.getByRole('button', { name: /克隆新音色/ }));

        expect(screen.getByText(/通过上传音频样板复刻特定人声/)).toBeInTheDocument();
        expect(screen.getByDisplayValue('cloned-voice')).toBeInTheDocument();
        expect(screen.getByText('test-audio.mp3')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /开始克隆/ })).toBeInTheDocument();
    });

    it('displays error and info messages', () => {
        const mockFile = new File(['dummy content'], 'test-audio.mp3', { type: 'audio/mpeg' });
        render(
            <VoiceClonePage
                clone={createVoiceCloneController({
                    cloneName: 'cloned-voice',
                    cloneError: 'Test error message',
                    cloneInfo: 'Test info message',
                    cloneAudioFile: mockFile
                })}
                errorRuntimeContext={{}}
            />
        );
        
        fireEvent.click(screen.getByRole('button', { name: /克隆新音色/ }));
        expect(screen.getByText('Test info message')).toBeInTheDocument();
        
        const form = screen.getByRole('button', { name: /开始克隆/ }).closest('form')!;
        fireEvent.submit(form);
        expect(screen.getByText('Test error message')).toBeInTheDocument();
    });

    it('switches between upload audio file and record microphone modes', () => {
        render(
            <VoiceClonePage
                clone={createVoiceCloneController({
                    cloneName: 'my-recorded-voice',
                    cloneAudioFile: null
                })}
                errorRuntimeContext={{}}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: /克隆新音色/ }));

        // Default is upload tab, which shows dropzone
        expect(screen.getByText(/点击或拖拽音频文件到此处上传/i)).toBeInTheDocument();

        // Click record tab
        const recordTabBtn = screen.getByRole('button', { name: /麦克风现场录制/i });
        fireEvent.click(recordTabBtn);

        // Record tab should reveal VoiceRecorder controls
        expect(screen.getByRole('button', { name: /开始录音/i })).toBeInTheDocument();
        expect(screen.getByText(/朗读示例范本/i)).toBeInTheDocument();

        // Switch back to upload tab
        const uploadTabBtn = screen.getByRole('button', { name: /上传音频文件/i });
        fireEvent.click(uploadTabBtn);
        expect(screen.getByText(/点击或拖拽音频文件到此处上传/i)).toBeInTheDocument();
    });

    it('supports selecting engine providers including Gemini', () => {
        const handleProviderChange = vi.fn();

        render(
            <VoiceClonePage
                clone={createVoiceCloneController()}
                errorRuntimeContext={{}}
                voiceProvider="gemini"
                onVoiceProviderChange={handleProviderChange}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: /克隆新音色/ }));

        const select = screen.getByRole('combobox');
        expect(select).toHaveValue('gemini');

        fireEvent.change(select, { target: { value: 'qwen' } });
        expect(handleProviderChange).toHaveBeenCalledWith('qwen');
    });

    it('requires a separate Gemini consent recording and exposes its upload', () => {
        const sample = new File(['sample'], 'sample.wav', { type: 'audio/wav' });
        const consent = new File(['consent'], 'consent.wav', { type: 'audio/wav' });
        const onConsentFileChange = vi.fn();
        const controller = createVoiceCloneController({
            cloneAudioFile: sample,
            onConsentFileChange,
        });
        const { rerender } = render(
            <VoiceClonePage clone={controller} errorRuntimeContext={{}} voiceProvider="gemini" />
        );
        fireEvent.click(screen.getByRole('button', { name: /克隆新音色/ }));
        expect(screen.getByRole('button', { name: /开始克隆/ })).toBeDisabled();
        expect(screen.getByText(/按顺序完成两步：先录制授权声明/)).toBeInTheDocument();
        const consentStep = screen.getByText(/第 1 步：授权声明录音/);
        const sampleStep = screen.getByText(/第 2 步：录制或上传自然语音样板/);
        expect(consentStep.compareDocumentPosition(sampleStep) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(screen.getByRole('button', { name: /上传音频文件/ })).toBeDisabled();
        expect(screen.getByRole('button', { name: /麦克风现场录制/ })).toBeDisabled();
        expect(screen.getByLabelText(/选择音频文件/)).toBeDisabled();
        expect(screen.getAllByText(/I am the owner of this voice and I consent to Google/)).toHaveLength(1);
        expect(screen.queryByText(/Google Gemini 声音复刻口述授权要求/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /上传授权录音/ }));
        expect(screen.getAllByText(/I am the owner of this voice and I consent to Google/)).toHaveLength(1);
        fireEvent.change(screen.getByLabelText(/选择授权录音/), { target: { files: [consent] } });
        expect(onConsentFileChange).toHaveBeenCalledWith(consent);

        rerender(
            <VoiceClonePage
                clone={{ ...controller, cloneConsentFile: consent, cloneCanSubmit: true }}
                errorRuntimeContext={{}}
                voiceProvider="gemini"
            />
        );
        expect(screen.getByRole('button', { name: /开始克隆/ })).toBeEnabled();
        expect(screen.getByRole('button', { name: /上传音频文件/ })).toBeEnabled();
        expect(screen.getByRole('button', { name: /麦克风现场录制/ })).toBeEnabled();
        expect(screen.getByLabelText(/选择音频文件/)).toBeEnabled();
    });

    it('shows a Gemini clone in the library and finds it by display name', () => {
        render(
            <VoiceClonePage
                clone={createVoiceCloneController({
                    cloneVoices: [{
                        voice: 'voice_my_gemini_clone',
                        name: 'My Gemini Voice',
                        type: 'voice_clone',
                        target_model: 'gemini-3.8-flash-tts',
                        provider: 'gemini',
                    }],
                })}
                errorRuntimeContext={{}}
            />
        );
        expect(screen.getByText('My Gemini Voice')).toBeInTheDocument();
        expect(screen.getByText('Gemini · Clone')).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('搜索克隆的音色…'), {
            target: { value: 'My Gemini Voice' },
        });
        expect(screen.getByText('My Gemini Voice')).toBeInTheDocument();
    });
});
