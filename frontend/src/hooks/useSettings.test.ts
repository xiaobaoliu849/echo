import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import useSettings from './useSettings';
import { createFormatErrorMessageStub } from '../test/factories';
import { updateSettings } from '../api';

vi.mock('../api', () => ({
    configureEverMemRuntime: vi.fn(),
    getEverMemRuntimeConfig: vi.fn().mockReturnValue({
        enabled: false,
        api_url: "",
        api_key: "",
        scope_id: "",
        temporary_session: false,
        remember_chat: true,
        remember_voice_chat: true,
        remember_recordings: false,
        remember_podcast: true,
        remember_tts: true,
        store_transcript_fulltext: false
    }),
    fetchApiRuntimeInfo: vi.fn().mockResolvedValue({}),
    fetchDesktopStatus: vi.fn().mockResolvedValue({
        runtime_dir: '/tmp/voicespirit-runtime',
        diagnostics_dir: '/tmp/voicespirit-runtime/diagnostics',
        preflight: {
            available: true,
            ok: false,
            timestamp: '2026-03-10T22:45:02+0800',
            failed_checks: [
                { name: 'desktop_app_route', detail: '/app route is not reachable' }
            ],
            failed_count: 1
        },
        latest_error: {
            available: true,
            timestamp: '2026-03-10T22:46:00+0800',
            error_type: 'RuntimeError',
            message: 'Backend is up, but /app is not reachable.',
            recovery_hints: [
                '确认 backend/main.py 仍挂载了 /app 和 /assets',
                '必要时清理桌面缓存：python run_web_desktop.py --clear-webview'
            ]
        }
    }),
    fetchSettings: vi.fn().mockResolvedValue({
        settings: {
            api_keys: { dashscope_api_key: 'sk-test' },
            api_urls: { DashScope: 'https://dashscope.example.com' },
            realtime_api_urls: {
                DashScope: 'wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'
            },
            default_models: {
                DashScope: {
                    default: 'qwen-plus',
                    available: ['qwen-plus', 'qwen-max']
                }
            },
            general_settings: {},
            memory_settings: {
                enabled: true,
                api_url: 'https://evermem.example.com',
                api_key: 'evermem-key',
                scope_id: 'workspace-main',
                temporary_session: false,
                remember_chat: true,
                remember_voice_chat: true,
                remember_recordings: false,
                remember_podcast: true,
                remember_tts: true,
                store_transcript_fulltext: false
            },
            output_directory: "",
            tts_settings: {},
            qwen_tts_settings: {},
            transcription_settings: {
                upload_mode: 's3',
                public_base_url: '',
                s3_bucket: 'voicespirit-assets',
                s3_region: 'us-east-1',
                s3_endpoint_url: '',
                s3_access_key_id: '',
                s3_secret_access_key: '',
                s3_key_prefix: 'transcription'
            },
            minimax: {},
            ui_settings: {
                remember_window_position: true,
                always_on_top: true,
                show_tray_icon: false
            },
            shortcuts: {
                wake_app: 'Ctrl+Alt+V'
            }
        },
        config_path: '',
        providers: ['DashScope']
    }),
    updateSettings: vi.fn()
}));

describe('useSettings', () => {
    it('initializes correctly', () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useSettings({ formatErrorMessage }));

        expect(result.current.settingsProvider).toBe('DashScope');
        expect(result.current.settingsBusy).toBe(true); // Initially fetching
    });

    it('builds grouped section metadata after settings load', async () => {
        const formatErrorMessage = createFormatErrorMessageStub();
        const { result } = renderHook(() => useSettings({ formatErrorMessage }));

        await waitFor(() => {
            expect(result.current.settingsBusy).toBe(false);
        });

        expect(result.current.providerSection.apiKeyConfigured).toBe(true);
        expect(result.current.settingsRealtimeApiUrl).toBe(
            'wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'
        );
        expect(result.current.providerSection.availableModelCount).toBe(2);
        expect(result.current.memorySection.configured).toBe(true);
        expect(result.current.memorySection.scenes.find((item) => item.id === 'transcription')?.enabled).toBe(false);
        expect(result.current.transcriptionSection.uploadMode).toBe('s3');
        expect(result.current.transcriptionSection.s3Configured).toBe(false);
        expect(result.current.transcriptionSection.s3MissingFields).toEqual([
            's3_access_key_id',
            's3_secret_access_key'
        ]);
        expect(result.current.desktopSection.rememberWindowPosition).toBe(true);
        expect(result.current.desktopSection.alwaysOnTop).toBe(true);
        expect(result.current.desktopSection.showTrayIcon).toBe(false);
        expect(result.current.desktopSection.wakeShortcut).toBe('Ctrl+Alt+V');
        expect(result.current.desktopSection.preflight.ok).toBe(false);
        expect(result.current.desktopSection.preflight.failed_count).toBe(1);
        expect(result.current.desktopSection.latestError.available).toBe(true);
        expect(result.current.desktopSection.latestError.recovery_hints).toContain(
            '必要时清理桌面缓存：python run_web_desktop.py --clear-webview'
        );
        expect(result.current.desktopSection.diagnosticsDir).toBe('/tmp/voicespirit-runtime/diagnostics');
    });

    it('persists the DashScope workspace realtime URL', async () => {
        const updateSettingsMock = vi.mocked(updateSettings);
        updateSettingsMock.mockClear();
        const { result } = renderHook(() =>
            useSettings({ formatErrorMessage: createFormatErrorMessageStub() })
        );

        await waitFor(() => expect(result.current.settingsBusy).toBe(false));
        act(() => {
            result.current.onRealtimeApiUrlChange(
                'wss://new-workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'
            );
        });
        await act(async () => {
            await result.current.onSubmit({ preventDefault: vi.fn() } as never);
        });

        expect(updateSettingsMock).toHaveBeenCalledWith(
            expect.objectContaining({
                realtime_api_urls: {
                    DashScope: 'wss://new-workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'
                }
            })
        );
    });

    it('persists Doubao provider settings without key mapping error', async () => {
        const updateSettingsMock = vi.mocked(updateSettings);
        updateSettingsMock.mockClear();
        updateSettingsMock.mockResolvedValue({
            config_path: '/tmp/config.json',
            providers: ['DashScope', 'Doubao'],
            settings: {} as any
        });
        const { result } = renderHook(() =>
            useSettings({ formatErrorMessage: createFormatErrorMessageStub() })
        );

        await waitFor(() => expect(result.current.settingsBusy).toBe(false));

        act(() => {
            result.current.onProviderChange('Doubao');
        });

        act(() => {
            result.current.onApiKeyChange('volc_test_key_123');
            result.current.onDoubaoAppIdChange('123456789');
            result.current.onRealtimeApiUrlChange('wss://openspeech.bytedance.com/api/v3/realtime/dialogue');
        });

        await act(async () => {
            await result.current.onSubmit({ preventDefault: vi.fn() } as never);
        });

        expect(result.current.settingsError).toBe('');
        expect(updateSettingsMock).toHaveBeenCalledWith(
            expect.objectContaining({
                api_keys: {
                    doubao_api_key: 'volc_test_key_123',
                    doubao_app_id: '123456789',
                    doubao_websearch_api_key: ''
                },
                realtime_api_urls: {
                    Doubao: 'wss://openspeech.bytedance.com/api/v3/realtime/dialogue'
                }
            })
        );
    });
});
