import { useState } from "react";
import {
  Cloud,
  HardDrive,
  ShieldCheck,
  Globe,
  Info,
  Sparkles,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Layers
} from "lucide-react";
import type { UseSettingsResult } from "../../hooks/useSettings";
import SecretInput from "./SecretInput";
import { useI18n } from "../../i18n";

type Props = {
  settings: UseSettingsResult;
};

interface CloudPreset {
  name: string;
  badge: string;
  region: string;
  endpointUrl: string;
  keyPrefix: string;
  exampleBaseUrl: string;
}

const CLOUD_PRESETS: CloudPreset[] = [
  {
    name: "Cloudflare R2",
    badge: "推荐 · 0出网费",
    region: "auto",
    endpointUrl: "https://<account_id>.r2.cloudflarestorage.com",
    keyPrefix: "transcription/",
    exampleBaseUrl: "https://pub-your-id.r2.dev"
  },
  {
    name: "阿里云 OSS",
    badge: "国内高速",
    region: "oss-cn-hangzhou",
    endpointUrl: "https://oss-cn-hangzhou.aliyuncs.com",
    keyPrefix: "transcription/",
    exampleBaseUrl: "https://your-bucket.oss-cn-hangzhou.aliyuncs.com"
  },
  {
    name: "腾讯云 COS",
    badge: "国内高速",
    region: "ap-guangzhou",
    endpointUrl: "https://cos.ap-guangzhou.myqcloud.com",
    keyPrefix: "transcription/",
    exampleBaseUrl: "https://your-bucket.cos.ap-guangzhou.myqcloud.com"
  },
  {
    name: "AWS S3",
    badge: "全球标准",
    region: "us-east-1",
    endpointUrl: "",
    keyPrefix: "transcription/",
    exampleBaseUrl: "https://your-bucket.s3.us-east-1.amazonaws.com"
  },
  {
    name: "MinIO",
    badge: "私有化部署",
    region: "us-east-1",
    endpointUrl: "http://127.0.0.1:9000",
    keyPrefix: "transcription/",
    exampleBaseUrl: "http://127.0.0.1:9000/your-bucket"
  }
];

export default function TranscriptionSettingsSection({ settings }: Props) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const [showFaq, setShowFaq] = useState(false);

  const mode = settings.transcriptionUploadMode || "static";

  // Compute live sample URL for clarity
  const cleanBaseUrl = settings.transcriptionPublicBaseUrl.trim().replace(/\/+$/, "");
  let sampleUrl = "";
  if (cleanBaseUrl) {
    if (mode === "s3") {
      const prefix = settings.transcriptionS3KeyPrefix.trim().replace(/^\/+|\/+$/g, "");
      sampleUrl = prefix ? `${cleanBaseUrl}/${prefix}/sample_speech.mp3` : `${cleanBaseUrl}/sample_speech.mp3`;
    } else if (mode === "static") {
      sampleUrl = `${cleanBaseUrl}/public/transcription/sample_speech.mp3`;
    }
  }

  const isUrlValid =
    !cleanBaseUrl ||
    cleanBaseUrl.startsWith("http://") ||
    cleanBaseUrl.startsWith("https://");

  const handleCopySampleUrl = () => {
    if (!sampleUrl) return;
    navigator.clipboard.writeText(sampleUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApplyPreset = (preset: CloudPreset) => {
    if (!settings.transcriptionS3Region) {
      settings.onTranscriptionS3RegionChange(preset.region);
    }
    if (!settings.transcriptionS3EndpointUrl && preset.endpointUrl) {
      settings.onTranscriptionS3EndpointUrlChange(preset.endpointUrl);
    }
    if (!settings.transcriptionS3KeyPrefix) {
      settings.onTranscriptionS3KeyPrefixChange(preset.keyPrefix);
    }
    if (!settings.transcriptionPublicBaseUrl && preset.exampleBaseUrl) {
      settings.onTranscriptionPublicBaseUrlChange(preset.exampleBaseUrl);
    }
  };

  return (
    <div className="vsSettingsCard vsTranscriptionSection">
      {/* ── 1. Hero Concept & Architecture Guide Banner ── */}
      <div className="vsTranscriptionHero">
        <div className="vsTranscriptionHeroTop">
          <div className="vsTranscriptionHeroBadge">
            <Layers size={18} className="hero-badge-icon" />
            <span className="hero-badge-text">
              {mode === "disabled" && t("当前：仅本地离线处理", "Current: Local Offline")}
              {mode === "static" && t("当前：本地静态托管", "Current: Local Static Hosting")}
              {mode === "s3" && t("当前：S3 存储直传", "Current: S3 Direct Upload")}
            </span>
          </div>
        </div>
        <div className="vsTranscriptionHeroCopy">
          <h2 className="hero-title">
            {t("云端长音频异步转写 · 媒体中转站", "Cloud Transcription · Media Relay Center")}
          </h2>
          <p className="hero-desc">
            {t(
              "当您使用云端大模型（如阿里百炼 Paraformer / SenseVoice 异步长转写）时，云端服务器无法直接读取本地电脑文件，需要由 Echo 提供一个公网可访问的下载地址供模型拉取。如果您仅使用本地 Whisper 模型，请选择「禁用公网分发」，无需配置任何云存储或域名。",
              "When using cloud AI models for long transcription, external servers cannot access your local disk and require a public audio URL. If you only use local Whisper models, choose 'Disable public distribution' to bypass all public uploads."
            )}
          </p>
          <div className="vsTranscriptionWorkflow">
            <div className="workflow-step">
              <span className="step-num">1</span>
              <span className="step-label">{t("本地音频文件", "Local Audio")}</span>
            </div>
            <span className="workflow-arrow">➔</span>
            <div className={`workflow-step ${mode !== "disabled" ? "active" : ""}`}>
              <span className="step-num">2</span>
              <span className="step-label">
                {mode === "s3" ? t("S3 对象存储中转", "S3 Storage Relay") : mode === "static" ? t("本地服务静态托管", "Local Web Hosting") : t("无需中转 (本地处理)", "No Relay Needed")}
              </span>
            </div>
            <span className="workflow-arrow">➔</span>
            <div className="workflow-step">
              <span className="step-num">3</span>
              <span className="step-label">{t("AI 模型拉取识别", "AI Model Transcription")}</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── 2. Interactive Mode Selection Cards ── */}
      <div className="vsCardSection">
        <div className="vsSectionHeaderWrap">
          <h3 className="vsCardSubTitle">{t("文件上传模式", "Upload Mode")}</h3>
          <span className="vsSectionSubHint">
            {t("控制生成的录音/视频文稿文件如何暂存于存储中供后端模型拉取及分享使用。", "Controls how generated recording/video transcript files are staged for backend model access and sharing.")}
          </span>
        </div>

        {/* Hidden/Native Select synced for test automation & accessibility */}
        <select
          data-testid="transcription-upload-mode"
          className="vsSelect visually-hidden-select"
          value={mode}
          onChange={(e) => settings.onTranscriptionUploadModeChange(e.target.value)}
          aria-label={t("文件上传模式", "Upload Mode")}
        >
          <option value="static">{t("本地静态发布 (Static)", "Local static hosting")}</option>
          <option value="s3">{t("S3 兼容对象存储 (S3 API)", "S3-compatible object storage")}</option>
          <option value="disabled">{t("禁用公网分发 (Disabled)", "Disable public distribution")}</option>
        </select>

        <div className="vsModeCardsGrid">
          {/* Card 1: Static */}
          <div
            className={`vsModeCard ${mode === "static" ? "selected" : ""}`}
            onClick={() => settings.onTranscriptionUploadModeChange("static")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && settings.onTranscriptionUploadModeChange("static")}
          >
            <div className="card-top">
              <div className="card-icon-wrap static">
                <HardDrive size={18} />
              </div>
              <span className="card-tag static">{t("配合内网穿透", "Tunnel / IP")}</span>
              <div className="card-radio-mark" />
            </div>
            <h4 className="card-title">{t("本地静态发布 (Static)", "Local static hosting")}</h4>
            <p className="card-desc">
              {t(
                "由 Echo 本地内置服务托管。需配合公网 IP、动态域名或内网穿透（如 cpolar / ngrok / Cloudflare Tunnel）。",
                "Hosted by Echo's local server. Requires a public IP or tunnel (e.g. cpolar / ngrok / Cloudflare Tunnel)."
              )}
            </p>
          </div>

          {/* Card 2: S3 API */}
          <div
            className={`vsModeCard ${mode === "s3" ? "selected" : ""}`}
            onClick={() => settings.onTranscriptionUploadModeChange("s3")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && settings.onTranscriptionUploadModeChange("s3")}
          >
            <div className="card-top">
              <div className="card-icon-wrap s3">
                <Cloud size={18} />
              </div>
              <span className="card-tag s3">{t("推荐 · 高可用", "Recommended")}</span>
              <div className="card-radio-mark" />
            </div>
            <h4 className="card-title">{t("S3 兼容对象存储 (S3 API)", "S3-compatible object storage")}</h4>
            <p className="card-desc">
              {t(
                "录音自动直传至云端存储桶，生成高可用下载直链。支持 Cloudflare R2、阿里云 OSS、腾讯云 COS、AWS S3 等。",
                "Audio auto-uploads to your S3 bucket. Works with Cloudflare R2, Aliyun OSS, Tencent COS, AWS S3, etc."
              )}
            </p>
          </div>

          {/* Card 3: Disabled */}
          <div
            className={`vsModeCard ${mode === "disabled" ? "selected" : ""}`}
            onClick={() => settings.onTranscriptionUploadModeChange("disabled")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && settings.onTranscriptionUploadModeChange("disabled")}
          >
            <div className="card-top">
              <div className="card-icon-wrap disabled">
                <ShieldCheck size={18} />
              </div>
              <span className="card-tag disabled">{t("纯本地 Whisper", "Local Only")}</span>
              <div className="card-radio-mark" />
            </div>
            <h4 className="card-title">{t("禁用公网分发 (Disabled)", "Disable public distribution")}</h4>
            <p className="card-desc">
              {t(
                "适合仅使用本地 Whisper 模型的用户。不上传任何音频至公网，完全离线计算，严格保护个人数据隐私。",
                "Ideal for local Whisper users. No files uploaded to the web, purely offline and privacy-first."
              )}
            </p>
          </div>
        </div>
      </div>

      {/* ── 3. Public Base URL & Live Preview (Shown for Static & S3) ── */}
      {mode !== "disabled" && (
        <div className="vsCardSection border-top">
          <div className="vsSectionHeaderWrap">
            <h3 className="vsCardSubTitle">{t("分发基础域名 (Public Base URL)", "Public Base URL")}</h3>
            <span className="vsSectionSubHint">
              {t("云端模型从外部拉取音频时所访问的公开根地址", "Public root URL that cloud models use to fetch your audio")}
            </span>
          </div>

          <label className="vsField">
            <span className="vsFieldLabel">{t("分发基础域名 (Public Base URL)", "Public Base URL")}</span>
            <div className="input-with-icon">
              <Globe size={16} className="input-leading-icon" />
              <input
                className={`vsInput has-icon ${!isUrlValid ? "input-error" : ""}`}
                value={settings.transcriptionPublicBaseUrl}
                onChange={(e) => settings.onTranscriptionPublicBaseUrlChange(e.target.value)}
                placeholder="https://files.example.com"
              />
            </div>
            {!isUrlValid && (
              <span className="vsFieldHint error-hint">
                <AlertCircle size={14} />
                {t("地址必须以 http:// 或 https:// 开头", "URL must start with http:// or https://")}
              </span>
            )}
            <span className="vsFieldHint">
              {t("文件上传结束后生成的访问根锚点。", "Root URL used to access uploaded files.")}
            </span>
          </label>

          {/* Live Preview Bar */}
          {cleanBaseUrl && (
            <div className="vsLiveUrlPreview">
              <div className="preview-header">
                <div className="preview-label">
                  <Sparkles size={14} className="sparkle-icon" />
                  <span>{t("云端实际拉取音频的链接示例", "Generated Sample Cloud Audio URL")}</span>
                </div>
                <button
                  type="button"
                  className="preview-copy-btn"
                  onClick={handleCopySampleUrl}
                  title={t("复制示例链接", "Copy sample URL")}
                >
                  {copied ? <Check size={13} className="text-ok" /> : <Copy size={13} />}
                  <span>{copied ? t("已复制", "Copied") : t("复制", "Copy")}</span>
                </button>
              </div>
              <code className="preview-code">{sampleUrl}</code>
            </div>
          )}
        </div>
      )}

      {/* ── 4. S3 Specific Settings & Provider Quick Presets ── */}
      {mode === "s3" && (
        <div className="vsCardSection border-top">
          <div className="vsSectionHeaderWrap">
            <h3 className="vsCardSubTitle">{t("S3 Bucket 连接参数", "S3 Bucket Connection")}</h3>
            <span className="vsSectionSubHint">
              {t("配置兼容 AWS S3 协议的对象存储凭据", "Configure credentials for your S3-compatible cloud bucket")}
            </span>
          </div>

          {/* Quick Presets */}
          <div className="vsPresetsWrap">
            <div className="presets-label">
              <Info size={14} />
              <span>{t("主流云存储厂商一键快捷建议：", "Quick Fill Presets:")}</span>
            </div>
            <div className="presets-buttons">
              {CLOUD_PRESETS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  className="vsPresetBtn"
                  onClick={() => handleApplyPreset(preset)}
                  title={`${preset.name} (${preset.badge})`}
                >
                  <span className="preset-name">{preset.name}</span>
                  <span className="preset-tag">{preset.badge}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="vsFormRow">
            <label className="vsField">
              <span className="vsFieldLabel">Bucket Name</span>
              <input
                className="vsInput"
                value={settings.transcriptionS3Bucket}
                onChange={(e) => settings.onTranscriptionS3BucketChange(e.target.value)}
                placeholder={t("例如: echo-assets", "For example: echo-assets")}
              />
              <span className="vsFieldHint">{t("存储桶名称", "Target S3 bucket name")}</span>
            </label>
            <label className="vsField">
              <span className="vsFieldLabel">{t("Region (区域代码)", "Region")}</span>
              <input
                className="vsInput"
                value={settings.transcriptionS3Region}
                onChange={(e) => settings.onTranscriptionS3RegionChange(e.target.value)}
                placeholder={t("例如: us-east-1", "For example: us-east-1")}
              />
              <span className="vsFieldHint">{t("云存储所在的机房区域代码，Cloudflare R2 填 auto", "Region code, use 'auto' for Cloudflare R2")}</span>
            </label>
          </div>

          <div className="vsFormRow">
            <label className="vsField">
              <span className="vsFieldLabel">{t("自定义 Endpoint URL", "Custom Endpoint URL")}</span>
              <input
                className="vsInput"
                value={settings.transcriptionS3EndpointUrl}
                onChange={(e) => settings.onTranscriptionS3EndpointUrlChange(e.target.value)}
                placeholder={t("例如: https://s3.example.com", "For example: https://s3.example.com")}
              />
              <span className="vsFieldHint">{t("第三方 S3 服务终结点。AWS 原生 S3 可留空", "Endpoint for third-party S3; leave blank for native AWS S3")}</span>
            </label>
            <label className="vsField">
              <span className="vsFieldLabel">{t("存储前缀 (Key Prefix)", "Key Prefix")}</span>
              <input
                className="vsInput"
                value={settings.transcriptionS3KeyPrefix}
                onChange={(e) => settings.onTranscriptionS3KeyPrefixChange(e.target.value)}
                placeholder={t("例如: voice-jobs/", "For example: voice-jobs/")}
              />
              <span className="vsFieldHint">{t("文件在 Bucket 内的存储目录前缀", "Directory path prefix inside your bucket")}</span>
            </label>
          </div>

          <div className="vsFormRow">
            <label className="vsField">
              <span className="vsFieldLabel">{t("访问凭证 ID (Access Key)", "Access Key ID")}</span>
              <input
                className="vsInput"
                type="password"
                value={settings.transcriptionS3AccessKeyId}
                onChange={(e) => settings.onTranscriptionS3AccessKeyIdChange(e.target.value)}
                placeholder={t("输入 Access Key ID", "Enter Access Key ID")}
              />
              <span className="vsFieldHint">{t("具有该 Bucket 读写权限的 AccessKey ID", "Access Key with PutObject permissions")}</span>
            </label>
            <label className="vsField">
              <span className="vsFieldLabel">{t("访问私钥 (Secret Key)", "Secret Access Key")}</span>
              <SecretInput
                value={settings.transcriptionS3SecretAccessKey}
                onChange={settings.onTranscriptionS3SecretAccessKeyChange}
                placeholder={t("输入 Secret Access Key", "Enter Secret Access Key")}
                section="transcription_settings"
                secretKey="s3_secret_access_key"
              />
              <span className="vsFieldHint">{t("保密保存，支持脱敏保护与查看", "Secret key, safely masked and encrypted")}</span>
            </label>
          </div>
        </div>
      )}

      {/* ── 5. Collapsible FAQ & Knowledge Tips ── */}
      <div className="vsTranscriptionFaq">
        <button
          type="button"
          className="faq-toggle-btn"
          onClick={() => setShowFaq((prev) => !prev)}
        >
          <div className="faq-toggle-left">
            <Info size={16} />
            <span>{t("关于文件转写与云存储的常见疑问 (FAQ)", "Frequently Asked Questions (FAQ)")}</span>
          </div>
          {showFaq ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {showFaq && (
          <div className="faq-content">
            <div className="faq-item">
              <strong>{t("1. 我只用电脑本地 Whisper 识别，需要配置这些吗？", "1. Do I need this if I only use local Whisper?")}</strong>
              <p>
                {t(
                  "完全不需要！直接选择上面的「禁用公网分发 (Disabled)」，此时音视频只在本地计算，不会上传任何数据，也不会产生任何公网费用。",
                  "Not at all! Select 'Disable public distribution (Disabled)'. Your audio stays strictly on your machine and incurs zero cloud costs."
                )}
              </p>
            </div>
            <div className="faq-item">
              <strong>{t("2. 什么是 Public Base URL（分发基础域名）？", "2. What is Public Base URL?")}</strong>
              <p>
                {t(
                  "当使用阿里百炼等云端模型时，云端服务器需要从外部下载您的音频文件。Public Base URL 就是该文件在互联网上可访问的根网址（例如 https://mybucket.r2.dev 或通过 cpolar/ngrok 穿透的域名）。",
                  "It is the root web address where the external cloud AI service can download your uploaded audio file over the internet."
                )}
              </p>
            </div>
            <div className="faq-item">
              <strong>{t("3. 推荐哪家云存储？", "3. Which cloud storage is recommended?")}</strong>
              <p>
                {t(
                  "强烈推荐 Cloudflare R2：提供每月 10GB 免费存储且完全免除出网流量费，性价比极高；国内用户也可使用阿里云 OSS 或腾讯云 COS。",
                  "Cloudflare R2 is highly recommended: 10GB free storage and zero egress fee. For domestic China users, Aliyun OSS or Tencent COS are also great options."
                )}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

