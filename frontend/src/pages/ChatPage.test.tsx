import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ChatPage from './ChatPage';
import { createChatController, createVoiceChatController } from '../test/factories';

describe('ChatPage', () => {
    it('allows selecting messages and copying an individual bubble', async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(globalThis.navigator, 'clipboard', {
            value: { writeText },
            configurable: true
        });
        render(
            <ChatPage
                chat={createChatController({
                    chatMessages: [
                        { role: 'user', content: 'Please copy this source.' },
                        { role: 'assistant', content: '请复制这条回复。' }
                    ]
                })}
                voiceChat={createVoiceChatController()}
                errorRuntimeContext={{}}
            />
        );

        const copyButtons = screen.getAllByRole('button', { name: '复制消息' });
        expect(document.querySelectorAll('.bubble.hasCopyAction')).toHaveLength(2);
        fireEvent.click(copyButtons[1]);

        await waitFor(() => expect(writeText).toHaveBeenCalledWith('请复制这条回复。'));
        expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();
    });

    it('renders correctly empty state', () => {
        render(
            <ChatPage
                chat={createChatController({ chatInput: 'hello' })}
                voiceChat={createVoiceChatController({ voiceChatProvider: "" })}
                errorRuntimeContext={{}}
            />
        );
        expect(screen.getByText(/Echo/)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: '发送' })).toBeInTheDocument();
        expect(screen.queryByText('实时语音')).not.toBeInTheDocument();
        expect(screen.queryByText(/麦克风按钮当前使用/)).not.toBeInTheDocument();
    });

    it('shows voice chat startup errors even when the realtime session failed to open', () => {
        render(
            <ChatPage
                chat={createChatController()}
                voiceChat={createVoiceChatController({
                    voiceChatStatus: '实时语音不可用',
                    voiceChatError: 'Google API Key 未配置，无法启动实时语音会话。'
                })}
                errorRuntimeContext={{}}
            />
        );

        expect(screen.getByText('实时语音')).toBeInTheDocument();
        expect(screen.getByText('Google API Key 未配置，无法启动实时语音会话。')).toBeInTheDocument();
    });

    it('allows text input and sends initial prompt to start realtime call for realtime models', () => {
        const mockStartPrompt = vi.fn();
        render(
            <ChatPage
                chat={createChatController({
                    chatProvider: 'DashScope',
                    chatModel: 'qwen3-omni-flash-realtime-2025-12-01',
                    chatInput: 'some input'
                })}
                voiceChat={createVoiceChatController({
                    startRecordingWithInitialPrompt: mockStartPrompt,
                })}
                errorRuntimeContext={{}}
            />
        );

        const textarea = screen.getByPlaceholderText(/输入文字发送启动实时会话/);
        expect(textarea).not.toBeDisabled();
        expect(screen.queryByRole('button', { name: '语音转写' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: '实时通话' })).toBeInTheDocument();
        const sendBtn = screen.getByRole('button', { name: '发送' });
        expect(sendBtn).not.toBeDisabled();

        fireEvent.click(sendBtn);
        expect(mockStartPrompt).toHaveBeenCalledWith('some input', []);
    });

    it('sends text and media directly to active live voice session during voice call', () => {
        const mockSendText = vi.fn();
        render(
            <ChatPage
                chat={createChatController({
                    chatProvider: 'Google',
                    chatModel: 'gemini-3.1-flash-live-preview',
                    chatInput: '帮我看下这个代码',
                    chatAttachments: [{ name: 'error.png', content: '[Image]', type: 'image', dataUrl: 'data:image/png;base64,123' }],
                })}
                voiceChat={createVoiceChatController({
                    voiceChatConnected: true,
                    voiceChatRecording: true,
                    sendTextMessage: mockSendText,
                })}
                errorRuntimeContext={{}}
            />
        );

        expect(screen.getByText(/已连接，您可以说话或打字/)).toBeInTheDocument();
        const sendBtn = screen.getByRole('button', { name: '发送' });
        expect(sendBtn).not.toBeDisabled();

        fireEvent.click(sendBtn);
        expect(mockSendText).toHaveBeenCalledWith('帮我看下这个代码', [
            { name: 'error.png', content: '[Image]', type: 'image', dataUrl: 'data:image/png;base64,123' }
        ]);
    });

    it('disables the realtime voice call button when a non-realtime text model is selected', () => {
        const mockToggle = vi.fn();
        render(
            <ChatPage
                chat={createChatController({
                    chatProvider: 'Google',
                    chatModel: 'gemini-3.7-flash',
                })}
                voiceChat={createVoiceChatController({
                    onToggleRecording: mockToggle,
                })}
                errorRuntimeContext={{}}
            />
        );

        const callButton = screen.getByRole('button', { name: '实时通话' });
        expect(callButton).toBeDisabled();
        expect(callButton).toHaveAttribute('title', expect.stringContaining('当前选择的是文本/多模态模型'));

        fireEvent.click(callButton);
        expect(mockToggle).not.toHaveBeenCalled();

        expect(screen.getByRole('button', { name: '语音转写' })).toBeInTheDocument();
    });

    it('shows memory badges for realtime voice turns', () => {
        render(
            <ChatPage
                chat={createChatController()}
                voiceChat={createVoiceChatController({
                    sessionSummary: [
                        { role: 'user', content: '这周重点是比赛提交，以后默认用中文回答。', memorySaved: true },
                        {
                            role: 'assistant',
                            content: '记住了，我会默认用中文回答。',
                            memoriesUsed: 1,
                            memorySourceSummary: '来源：本地待同步 1 条，云端 0 条'
                        }
                    ]
                })}
                errorRuntimeContext={{}}
            />
        );

        expect(screen.getByText('✓ 已记忆')).toBeInTheDocument();
        expect(screen.getByText(/🧠 回忆了 1 条/)).toBeInTheDocument();
        expect(screen.getByText('来源：本地待同步 1 条，云端 0 条')).toBeInTheDocument();
    });

    it('renders native tool progress and grounded sources during a live call', () => {
        render(
            <ChatPage
                chat={createChatController()}
                voiceChat={createVoiceChatController({
                    voiceChatRecording: true,
                    voiceChatConnected: true,
                    voiceChatAgentToolStatus: '正在搜索网页资料…',
                    voiceChatAgentRunMeta: 'search_web · 820 ms',
                    voiceChatAgentSources: [
                        {
                            title: 'Gemini Live tools',
                            uri: 'https://ai.google.dev/gemini-api/docs/live-api/tools',
                            snippet: 'Function calling documentation',
                            source_type: 'web'
                        }
                    ]
                })}
                errorRuntimeContext={{}}
            />
        );

        expect(screen.getAllByText('正在搜索网页资料…').length).toBeGreaterThan(0);
        expect(screen.getByRole('status')).toHaveTextContent('search_web · 820 ms');
        expect(screen.getByRole('link', { name: 'Gemini Live tools' })).toHaveAttribute(
            'href',
            'https://ai.google.dev/gemini-api/docs/live-api/tools'
        );
    });

    it('shows live translate controls and bilingual streaming labels for Gemini Live Translate', () => {
        render(
            <ChatPage
                chat={createChatController({
                    chatProvider: 'Google',
                    chatModel: 'gemini-3.5-live-translate-preview'
                })}
                voiceChat={createVoiceChatController({
                    voiceChatModel: 'gemini-3.5-live-translate-preview',
                    voiceChatVoiceLabel: 'Puck',
                    voiceChatLiveTranslate: true,
                    voiceChatSourceLanguageCode: 'en',
                    voiceChatTargetLanguageCode: 'zh-Hans',
                    voiceChatTargetLanguageLabel: '中文（简体）/ Chinese (Simplified) (zh-Hans)',
                    voiceChatTargetLanguageOptions: [
                        { value: 'en', label: 'English (en)' },
                        { value: 'zh-Hans', label: '中文（简体）(zh-Hans)' }
                    ],
                    voiceChatRecording: true,
                    voiceChatConnected: true,
                    voiceChatTranscript: 'Hello everyone',
                    voiceChatReply: '大家好'
                })}
                errorRuntimeContext={{}}
            />
        );

        expect(screen.getByTitle('通话设置')).toBeDisabled();
        // Live-translate badge shows the target language only (source is
        // auto-detected), not the stale TTS voice label
        expect(document.querySelector('.vsVoiceModelBadge')).toHaveTextContent(
            'Google / gemini-3.5-live-translate-preview · 单向翻译 (→ 中文)'
        );
        expect(screen.getByText('原文实时转写')).toBeInTheDocument();
        expect(screen.getByText('译文：中文（简体）/ Chinese (Simplified) (zh-Hans)')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: '复制实时原文' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: '复制实时译文' })).toBeInTheDocument();
        expect(screen.queryByPlaceholderText(/输入聊天内容/)).not.toBeInTheDocument();
        expect(document.querySelector('.vsComposer.liveActive')).toBeInTheDocument();
    });

    it('uses English voice for English assistant messages when default voice is Chinese', async () => {
        const fetchSpeakAudioMock = vi.spyOn(await import('../api'), 'fetchSpeakAudio').mockResolvedValue({
            blob: new Blob(['audio'], { type: 'audio/mpeg' }),
            voice: 'en-US-AvaNeural',
            engine: 'edge',
            memorySaved: false
        });

        render(
            <ChatPage
                chat={createChatController({
                    chatMessages: [
                        { role: 'assistant', content: 'Hello, this is an English response from LLM.' }
                    ]
                })}
                voiceChat={createVoiceChatController()}
                settings={{
                    settingsData: {
                        tts_settings: {
                            provider: 'edge',
                            default_voice: 'zh-CN-XiaoxiaoNeural'
                        }
                    }
                } as any}
                errorRuntimeContext={{}}
            />
        );

        const playBtn = screen.getByRole('button', { name: '朗读回答' });
        fireEvent.click(playBtn);

        await waitFor(() => {
            expect(fetchSpeakAudioMock).toHaveBeenCalledWith({
                text: 'Hello, this is an English response from LLM.',
                voice: 'en-US-AvaNeural',
                engine: 'edge'
            });
        });
    });

    it('uses Japanese voice for Japanese assistant messages when default voice is Chinese', async () => {
        const fetchSpeakAudioMock = vi.spyOn(await import('../api'), 'fetchSpeakAudio').mockResolvedValue({
            blob: new Blob(['audio'], { type: 'audio/mpeg' }),
            voice: 'ja-JP-NanamiNeural',
            engine: 'edge',
            memorySaved: false
        });

        render(
            <ChatPage
                chat={createChatController({
                    chatMessages: [
                        { role: 'assistant', content: 'こんにちは、今日は良い天気ですね。' }
                    ]
                })}
                voiceChat={createVoiceChatController()}
                settings={{
                    settingsData: {
                        tts_settings: {
                            provider: 'edge',
                            default_voice: 'zh-CN-XiaoxiaoNeural'
                        }
                    }
                } as any}
                errorRuntimeContext={{}}
            />
        );

        const playBtn = screen.getByRole('button', { name: '朗读回答' });
        fireEvent.click(playBtn);

        await waitFor(() => {
            expect(fetchSpeakAudioMock).toHaveBeenCalledWith({
                text: 'こんにちは、今日は良い天気ですね。',
                voice: 'ja-JP-NanamiNeural',
                engine: 'edge'
            });
        });
    });

    it('toggles web search sources card when search badge is clicked', () => {
        render(
            <ChatPage
                chat={createChatController({
                    chatMessages: [
                        {
                            role: 'assistant',
                            content: '这是根据搜索回答的内容',
                            toolCalls: [
                                {
                                    tool_name: 'search_web',
                                    status: 'completed',
                                    query: 'Python 3.14 特性',
                                    source_count: 1,
                                    elapsed_ms: 1200,
                                    sources: [
                                        {
                                            title: 'Python 3.14 Release Notes',
                                            uri: 'https://docs.python.org/3.14/whatsnew/3.14.html',
                                            snippet: 'Summary of new features in Python 3.14',
                                            source_type: 'web_search'
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                })}
                voiceChat={createVoiceChatController()}
                errorRuntimeContext={{}}
            />
        );

        expect(screen.queryByText(/搜索关键词/)).not.toBeInTheDocument();
        const searchBadge = screen.getByText(/🔍 联网搜索 · 1 来源 · 1.2s/);
        expect(searchBadge).toHaveClass('clickable');

        fireEvent.click(searchBadge);
        expect(screen.getByText(/Python 3.14 特性/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Python 3.14 Release Notes/ })).toHaveAttribute(
            'href',
            'https://docs.python.org/3.14/whatsnew/3.14.html'
        );
        expect(screen.getByText('Summary of new features in Python 3.14')).toBeInTheDocument();
    });

    it('renders deep thinking collapsible block when reasoningContent is present', () => {
        render(
            <ChatPage
                chat={createChatController({
                    chatMessages: [
                        {
                            role: 'assistant',
                            content: '最终回答',
                            reasoningContent: '第一步：分析用户需求...\n第二步：查找相关信息...'
                        }
                    ]
                })}
                voiceChat={createVoiceChatController()}
                errorRuntimeContext={{}}
            />
        );

        expect(screen.getByText('🧠')).toBeInTheDocument();
        expect(screen.getByText('深度思考')).toBeInTheDocument();
        expect(screen.getByText(/第一步：分析用户需求/)).toBeInTheDocument();

        fireEvent.click(screen.getByText('深度思考'));
        expect(screen.queryByText(/第一步：分析用户需求/)).not.toBeInTheDocument();
    });
});

