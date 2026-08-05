import React, { useCallback, useState } from 'react';
import { useI18n } from "../i18n";

type AudioDropZoneProps = {
    onFileDrop: (file: File) => void;
    selectedFile?: File | null;
    mainText?: string;
    subText?: string;
    readyText?: string;
    isProcessing?: boolean;
    inputLabel?: string;
};

export const AudioDropZone: React.FC<AudioDropZoneProps> = ({
    onFileDrop,
    selectedFile: controlledSelectedFile,
    mainText,
    subText,
    readyText,
    isProcessing = false,
    inputLabel
}) => {
    const { t } = useI18n();
    const [isDragging, setIsDragging] = useState(false);
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const displayFile = controlledSelectedFile === undefined ? selectedFile : controlledSelectedFile;
    const resolvedMainText = mainText ?? t("拖拽或选择要转写的音频", "Drag or select audio for transcription");
    const resolvedSubText = subText ?? t("支持 MP3, WAV, M4A", "Supports MP3, WAV, M4A");
    const resolvedReadyText = readyText ?? t("已就绪", "Ready");
    const resolvedInputLabel = inputLabel ?? t("选择音频文件", "Choose an audio file");

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
    }, []);

    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            setIsDragging(false);
            const file = e.dataTransfer.files[0];
            // Accept audio and video containers — the backend extracts the
            // audio track from video files via ffmpeg before transcription.
            if (
                file &&
                (file.type.startsWith('audio/') ||
                    file.type.startsWith('video/') ||
                    // Some OS/browser combos report an empty type for known
                    // containers (e.g. .mkv); fall back to the extension.
                    /\.(mp3|wav|flac|m4a|aac|mp4|ogg|opus|webm|mkv|mov|avi|flv|wmv|m4v|ts|3gp|mpg|mpeg)$/i.test(file.name))
            ) {
                setSelectedFile(file);
                onFileDrop(file);
            } else {
                alert(t("不支持的文件格式，请上传音频或视频文件。", "Unsupported file type. Please upload an audio or video file."));
            }
        },
        [onFileDrop, t]
    );

    const handleFileChange = useCallback(
        (e: React.ChangeEvent<HTMLInputElement>) => {
            const file = e.target.files?.[0];
            if (file) {
                setSelectedFile(file);
                onFileDrop(file);
            }
        },
        [onFileDrop]
    );

    return (
        <div
            className={`vsAudioDropZone ${isDragging ? "dragging" : ""} ${displayFile ? "has-file" : ""}`}
            style={{
                position: "relative",
                width: "100%",
                height: "180px",
                border: "2px dashed var(--line)",
                borderRadius: "14px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                transition: "all 0.2s",
                background: isDragging ? "rgba(107, 76, 246, 0.05)" : "#fff",
                borderColor: isDragging ? "var(--brand)" : displayFile ? "#10b981" : "var(--line)",
                cursor: "pointer",
                overflow: "hidden"
            }}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
        >
            <input
                type="file"
                accept="audio/*,video/*,.mkv,.mov,.avi,.flv,.wmv,.m4v,.ts,.3gp,.mpg,.mpeg,.opus,.flac,.m4a,.aac"
                onChange={handleFileChange}
                style={{
                    position: "absolute",
                    inset: 0,
                    width: "100%",
                    height: "100%",
                    opacity: 0,
                    cursor: "pointer",
                    zIndex: 10
                }}
                title=""
                aria-label={resolvedInputLabel}
                disabled={isProcessing}
            />

            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", pointerEvents: "none", textAlign: "center", padding: "0 20px" }}>
                {displayFile ? (
                    <>
                        <div style={{ fontSize: "40px", marginBottom: "12px" }}>💿</div>
                        <p style={{ margin: 0, fontSize: "15px", fontWeight: "600", color: "var(--text)" }}>
                            {displayFile?.name}
                        </p>
                        <p style={{ margin: "4px 0 0", fontSize: "13px", color: "#10b981", fontWeight: "500" }}>
                            {resolvedReadyText}
                        </p>
                    </>
                ) : (
                    <>
                        <div style={{ fontSize: "40px", marginBottom: "12px" }}>🎵</div>
                        <p style={{ margin: 0, fontSize: "16px", fontWeight: "600", color: "var(--text)" }}>
                            {resolvedMainText}
                        </p>
                        <p style={{ margin: "8px 0 0", fontSize: "12px", color: "var(--muted)" }}>
                            {resolvedSubText}
                        </p>
                    </>
                )}
            </div>
        </div>
    );
};
