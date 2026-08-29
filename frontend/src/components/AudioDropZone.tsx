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

function formatFileSize(bytes: number): string {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

const SUPPORTED_FORMAT_PILLS = ["MP3", "WAV", "M4A", "FLAC", "MP4", "MKV", "MOV", "AAC", "OGG"];

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
    const resolvedMainText = mainText ?? t("拖拽音视频文件至此处，或点击浏览选择", "Drag audio/video file here, or click to browse");
    const resolvedSubText = subText ?? t("支持所有常见音视频格式，视频将自动抽取音轨", "Supports all audio/video formats. Audio track extracted automatically.");
    const resolvedReadyText = readyText ?? t("文件已就绪，可开始转写", "Ready for transcription");
    const resolvedInputLabel = inputLabel ?? t("选择音视频文件", "Choose an audio or video file");

    const isVideoFile = displayFile ? /\.(mp4|mkv|mov|avi|flv|wmv|m4v|ts|3gp|mpg|mpeg)$/i.test(displayFile.name) || displayFile.type.startsWith("video/") : false;

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
            if (
                file &&
                (file.type.startsWith('audio/') ||
                    file.type.startsWith('video/') ||
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
                minHeight: "190px",
                border: isDragging ? "2px dashed var(--brand, #6366f1)" : displayFile ? "2px solid rgba(16, 185, 129, 0.45)" : "2px dashed var(--line)",
                borderRadius: "16px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                transition: "all 0.22s cubic-bezier(0.16, 1, 0.3, 1)",
                background: isDragging
                    ? "rgba(99, 102, 241, 0.06)"
                    : displayFile
                    ? "linear-gradient(180deg, rgba(16, 185, 129, 0.04) 0%, rgba(16, 185, 129, 0.01) 100%)"
                    : "var(--bg-card)",
                boxShadow: isDragging
                    ? "0 0 0 4px rgba(99, 102, 241, 0.12), 0 8px 24px rgba(99, 102, 241, 0.08)"
                    : displayFile
                    ? "0 4px 16px rgba(16, 185, 129, 0.06)"
                    : "none",
                cursor: "pointer",
                overflow: "hidden",
                padding: "24px 20px",
                boxSizing: "border-box",
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

            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", pointerEvents: "none", textAlign: "center", width: "100%" }}>
                {displayFile ? (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px" }}>
                        <div
                            style={{
                                width: "54px",
                                height: "54px",
                                borderRadius: "14px",
                                background: isVideoFile ? "linear-gradient(135deg, #ec4899, #8b5cf6)" : "linear-gradient(135deg, #10b981, #06b6d4)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: "26px",
                                color: "#fff",
                                boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
                                marginBottom: "4px",
                            }}
                        >
                            {isVideoFile ? "🎬" : "🎵"}
                        </div>
                        <p style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "var(--text)", maxWidth: "480px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {displayFile.name}
                        </p>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", justifyContent: "center" }}>
                            <span style={{ fontSize: "12px", color: "var(--muted)", background: "var(--bg-subtle, rgba(0,0,0,0.05))", padding: "2px 8px", borderRadius: "999px", fontWeight: 500 }}>
                                📦 {formatFileSize(displayFile.size)}
                            </span>
                            <span style={{ fontSize: "12px", color: isVideoFile ? "#9333ea" : "#059669", background: isVideoFile ? "rgba(147, 51, 234, 0.1)" : "rgba(16, 185, 129, 0.12)", padding: "2px 8px", borderRadius: "999px", fontWeight: 600 }}>
                                {isVideoFile ? t("🎬 视频音轨", "🎬 Video Audio") : t("🎵 音频", "🎵 Audio")}
                            </span>
                            <span style={{ fontSize: "12px", color: "#059669", background: "rgba(16, 185, 129, 0.12)", padding: "2px 8px", borderRadius: "999px", fontWeight: 600 }}>
                                🟢 {resolvedReadyText}
                            </span>
                        </div>
                        <p style={{ margin: "6px 0 0", fontSize: "12px", color: "var(--muted)", opacity: 0.85 }}>
                            {t("点击或拖拽其他文件可直接更换", "Click or drag another file to replace")}
                        </p>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "6px" }}>
                        <div
                            style={{
                                width: "52px",
                                height: "52px",
                                borderRadius: "14px",
                                background: isDragging ? "var(--brand, #6366f1)" : "var(--bg-subtle, rgba(99, 102, 241, 0.08))",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: "24px",
                                marginBottom: "4px",
                                transition: "all 0.2s ease",
                            }}
                        >
                            {isDragging ? "✨" : "🎧"}
                        </div>
                        <p style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "var(--text)" }}>
                            {resolvedMainText}
                        </p>
                        <p style={{ margin: "2px 0 8px", fontSize: "13px", color: "var(--muted)", maxWidth: "460px", lineHeight: 1.4 }}>
                            {resolvedSubText}
                        </p>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", justifyContent: "center" }}>
                            {SUPPORTED_FORMAT_PILLS.map((fmt) => (
                                <span
                                    key={fmt}
                                    style={{
                                        fontSize: "11px",
                                        fontWeight: 600,
                                        color: "var(--muted)",
                                        background: "var(--bg-subtle, rgba(0,0,0,0.04))",
                                        padding: "2px 6px",
                                        borderRadius: "4px",
                                        letterSpacing: "0.5px",
                                    }}
                                >
                                    {fmt}
                                </span>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
