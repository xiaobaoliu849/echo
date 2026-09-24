import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import VoiceDesignPage from './VoiceDesignPage';
import { createVoiceDesignController } from '../test/factories';

describe('VoiceDesignPage', () => {
    it('renders correctly', () => {
        render(
            <VoiceDesignPage
                design={createVoiceDesignController({
                    designName: 'test-voice',
                    designLanguage: 'en',
                    designPrompt: 'A test prompt',
                    designPreviewText: 'Hello world'
                })}
                errorRuntimeContext={{}}
            />
        );
        
        expect(screen.getByText('暂无设计的音色')).toBeInTheDocument();
        
        fireEvent.click(screen.getByRole('button', { name: /设计新音色/ }));

        expect(screen.getByText(/通过自然语言描述/)).toBeInTheDocument();
        expect(screen.getByDisplayValue('test-voice')).toBeInTheDocument();
        expect(screen.getByDisplayValue('en')).toBeInTheDocument();
        expect(screen.getByDisplayValue('A test prompt')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Hello world')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /开始创造/ })).toBeInTheDocument();
    });

    it('displays error and info messages', () => {
        render(
            <VoiceDesignPage
                design={createVoiceDesignController({
                    designName: 'test-voice',
                    designLanguage: 'zh',
                    designPrompt: 'test prompt',
                    designPreviewText: 'test preview',
                    designError: 'Test error message',
                    designInfo: 'Test info message'
                })}
                errorRuntimeContext={{}}
            />
        );
        
        fireEvent.click(screen.getByRole('button', { name: /设计新音色/ }));
        expect(screen.getByText('Test info message')).toBeInTheDocument();
        
        const form = screen.getByRole('button', { name: /开始创造/ }).closest('form')!;
        fireEvent.submit(form);
        expect(screen.getByText('Test error message')).toBeInTheDocument();
    });

    it('finds earlier designs by name and deletes through their provider', () => {
        const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
        const design = createVoiceDesignController({
            designVoices: [
                { voice: 'qwen-id', name: 'Earlier narrator', provider: 'qwen', type: 'voice_design', target_model: 'qwen3-tts-vd' },
                { voice: 'gemini-id', name: 'New narrator', provider: 'gemini', type: 'voice_design', target_model: 'gemini-3.8-flash-tts' }
            ]
        });
        render(<VoiceDesignPage design={design} errorRuntimeContext={{}} />);

        expect(screen.getByText('Earlier narrator')).toBeInTheDocument();
        expect(screen.getByText('New narrator')).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('搜索设计的音色…'), { target: { value: 'Earlier' } });
        expect(screen.getByText('Earlier narrator')).toBeInTheDocument();
        expect(screen.queryByText('New narrator')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: '删除' }));
        expect(design.onDeleteVoice).toHaveBeenCalledWith('qwen-id', 'qwen');
        confirm.mockRestore();
    });

    it('marks Xiaomi designs as previews in the creation form', () => {
        render(<VoiceDesignPage design={createVoiceDesignController()} errorRuntimeContext={{}} voiceProvider="xiaomi" />);
        fireEvent.click(screen.getByRole('button', { name: /设计新音色/ }));
        expect(screen.getByText(/只返回本次试听音频/)).toBeInTheDocument();
    });

    it('shows catalog failures in the library instead of silently showing an empty state', () => {
        render(<VoiceDesignPage design={createVoiceDesignController({ designError: 'qwen: catalog unavailable' })} errorRuntimeContext={{}} />);
        expect(screen.getByRole('alert')).toHaveTextContent('catalog unavailable');
        expect(screen.getByText('音色库暂不可用')).toBeInTheDocument();
        expect(screen.queryByText('暂无设计的音色')).not.toBeInTheDocument();
    });
});
