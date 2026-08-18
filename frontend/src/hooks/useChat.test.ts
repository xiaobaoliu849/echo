import { renderHook, act } from '@testing-library/react';
import { afterEach, describe, it, expect, vi } from 'vitest';

const {
    streamChatCompletionMock,
    ensureEverMemConversationGroupIdMock,
} = vi.hoisted(() => ({
    streamChatCompletionMock: vi.fn(),
    ensureEverMemConversationGroupIdMock: vi.fn(),
}));

vi.mock('../api', async () => {
    const actual = await vi.importActual<typeof import('../api')>('../api');
    return {
        ...actual,
        streamChatCompletion: streamChatCompletionMock,
        ensureEverMemConversationGroupId: ensureEverMemConversationGroupIdMock,
    };
});

import { persistEverMemConversationGroupId } from '../api';
import useChat from './useChat';
import { createFormatErrorMessageStub } from '../test/factories';

describe('useChat', () => {
    afterEach(() => {
        localStorage.clear();
        ensureEverMemConversationGroupIdMock.mockReset();
        streamChatCompletionMock.mockReset();
        vi.clearAllMocks();
    });

    it('initializes correctly', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() =>
            useChat({
                formatErrorMessage,
                providerOptions: ['DashScope', 'Google'],
                preferredProvider: 'DashScope',
                providerModelCatalog: {
                    DashScope: {
                        defaultModel: 'qwen-plus',
                        availableModels: ['qwen-plus', 'qwen-max']
                    },
                    Google: {
                        defaultModel: 'gemini-2.5-flash',
                        availableModels: ['gemini-2.5-flash']
                    }
                }
            })
        );

        expect(result.current.chatProvider).toBe('DashScope');
        expect(result.current.chatProviderOptions).toEqual(['DashScope', 'Google']);
        expect(result.current.chatModel).toBe('qwen-plus');
        expect(result.current.chatModelOptions).toEqual(['qwen-plus', 'qwen-max']);
        expect(result.current.chatInput).toBe('');
        expect(result.current.chatMessages).toEqual([]);

        act(() => {
            result.current.onInputChange('Hello');
        });

        expect(result.current.chatInput).toBe('Hello');
    });

    it('switches model defaults when provider changes', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() =>
            useChat({
                formatErrorMessage,
                providerOptions: ['DashScope', 'Google'],
                preferredProvider: 'DashScope',
                providerModelCatalog: {
                    DashScope: {
                        defaultModel: 'qwen-plus',
                        availableModels: ['qwen-plus', 'qwen-max']
                    },
                    Google: {
                        defaultModel: 'gemini-2.5-flash',
                        availableModels: ['gemini-2.5-flash', 'gemini-2.5-pro']
                    }
                }
            })
        );

        act(() => {
            result.current.onProviderChange('Google');
        });

        expect(result.current.chatProvider).toBe('Google');
        expect(result.current.chatModel).toBe('gemini-2.5-flash');
        expect(result.current.chatModelOptions).toEqual(['gemini-2.5-flash', 'gemini-2.5-pro']);
    });

    it('exposes enabled models from every provider in the main model picker', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() =>
            useChat({
                formatErrorMessage,
                providerOptions: ['DashScope', 'Google', 'Xiaomi'],
                preferredProvider: 'DashScope',
                providerModelCatalog: {
                    DashScope: {
                        defaultModel: 'qwen-plus',
                        availableModels: ['qwen-plus', 'qwen-max'],
                        enabledModels: ['qwen-plus']
                    },
                    Google: {
                        defaultModel: 'gemini-2.5-flash',
                        availableModels: ['gemini-2.5-flash', 'gemini-2.5-pro'],
                        enabledModels: ['gemini-2.5-pro']
                    },
                    Xiaomi: {
                        defaultModel: 'mimo-v2.5-pro',
                        availableModels: ['mimo-v2.5-pro', 'mimo-v2.5'],
                        enabledModels: ['mimo-v2.5-pro']
                    }
                }
            })
        );

        expect(result.current.chatModelChoices.map((item) => item.label)).toEqual([
            'DashScope / qwen-plus',
            'Google / gemini-2.5-flash',
            'Google / gemini-2.5-pro',
            'Xiaomi / mimo-v2.5-pro'
        ]);

        act(() => {
            result.current.onModelChoiceChange(result.current.chatModelChoices[2].value);
        });

        expect(result.current.chatProvider).toBe('Google');
        expect(result.current.chatModel).toBe('gemini-2.5-pro');
    });

    it('prefers a non-realtime text model when the configured default is a voice-only model', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() =>
            useChat({
                formatErrorMessage,
                providerOptions: ['DashScope'],
                preferredProvider: 'DashScope',
                providerModelCatalog: {
                    DashScope: {
                        defaultModel: 'qwen3-omni-flash-realtime-2025-12-01',
                        availableModels: [
                            'qwen3-omni-flash-realtime-2025-12-01',
                            'qwen-plus',
                            'qwen-max'
                        ]
                    }
                }
            })
        );

        expect(result.current.chatModel).toBe('qwen-plus');
        expect(result.current.chatModelOptions).toEqual([
            'qwen3-omni-flash-realtime-2025-12-01',
            'qwen-plus',
            'qwen-max'
        ]);
    });

    it('blocks text submission with a realtime-only model', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();

        const { result } = renderHook(() =>
            useChat({
                formatErrorMessage,
                providerOptions: ['DashScope'],
                preferredProvider: 'DashScope',
                providerModelCatalog: {
                    DashScope: {
                        defaultModel: 'qwen3-omni-flash-realtime-2025-12-01',
                        availableModels: ['qwen3-omni-flash-realtime-2025-12-01']
                    }
                }
            })
        );

        act(() => {
            result.current.onInputChange('hi');
        });
        await act(async () => {
            await result.current.onSubmit({ preventDefault() { } } as any);
        });

        expect(streamChatCompletionMock).not.toHaveBeenCalled();
        expect(ensureEverMemConversationGroupIdMock).not.toHaveBeenCalled();
        expect(result.current.chatError).toContain('实时语音/实时翻译模型');
    });

    it('reuses the same EverMem group id until starting a new session', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        ensureEverMemConversationGroupIdMock
            .mockResolvedValueOnce('group-chat-001')
            .mockResolvedValueOnce('group-chat-001')
            .mockResolvedValueOnce('group-chat-002');
        streamChatCompletionMock.mockImplementation(async (_payload, handlers, options) => {
            handlers.onDelta('ok');
            handlers.onDone?.({ memoriesRetrieved: 0, memorySaved: false });
            return options;
        });

        const { result } = renderHook(() =>
            useChat({
                formatErrorMessage,
                providerOptions: ['DashScope'],
                preferredProvider: 'DashScope',
                providerModelCatalog: {
                    DashScope: {
                        defaultModel: 'qwen-plus',
                        availableModels: ['qwen-plus']
                    }
                }
            })
        );

        act(() => {
            result.current.onInputChange('继续昨天的');
        });
        await act(async () => {
            await result.current.onSubmit({ preventDefault() { } } as any);
        });

        act(() => {
            result.current.onInputChange('再补一句');
        });
        await act(async () => {
            await result.current.onSubmit({ preventDefault() { } } as any);
        });

        act(() => {
            result.current.onNewSession();
            result.current.onInputChange('新会话');
        });
        await act(async () => {
            await result.current.onSubmit({ preventDefault() { } } as any);
        });

        expect(ensureEverMemConversationGroupIdMock.mock.calls).toEqual([
            ['chat', ''],
            ['chat', 'group-chat-001'],
            ['chat', ''],
        ]);
        expect(streamChatCompletionMock.mock.calls[0][2]).toMatchObject({ memoryGroupId: 'group-chat-001' });
        expect(streamChatCompletionMock.mock.calls[1][2]).toMatchObject({ memoryGroupId: 'group-chat-001' });
        expect(streamChatCompletionMock.mock.calls[2][2]).toMatchObject({ memoryGroupId: 'group-chat-002' });
    });

    it('restores a persisted EverMem group id on a fresh hook mount', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        persistEverMemConversationGroupId('chat', 'group-chat-restore');
        ensureEverMemConversationGroupIdMock.mockImplementation(async (_scene, currentGroupId) => currentGroupId);
        streamChatCompletionMock.mockImplementation(async (_payload, handlers) => {
            handlers.onDelta('ok');
            handlers.onDone?.({ memoriesRetrieved: 0, memorySaved: false });
        });

        const { result } = renderHook(() =>
            useChat({
                formatErrorMessage,
                providerOptions: ['DashScope'],
                preferredProvider: 'DashScope',
                providerModelCatalog: {
                    DashScope: {
                        defaultModel: 'qwen-plus',
                        availableModels: ['qwen-plus']
                    }
                }
            })
        );

        act(() => {
            result.current.onInputChange('恢复旧会话');
        });
        await act(async () => {
            await result.current.onSubmit({ preventDefault() { } } as any);
        });

        expect(ensureEverMemConversationGroupIdMock).toHaveBeenCalledWith('chat', 'group-chat-restore');
        expect(streamChatCompletionMock.mock.calls[0][2]).toMatchObject({ memoryGroupId: 'group-chat-restore' });
    });
});
