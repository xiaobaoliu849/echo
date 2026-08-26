import type { UseSettingsResult } from "../../hooks/useSettings";
import SecretInput from "./SecretInput";
import { useI18n } from "../../i18n";

type Props = {
  settings: UseSettingsResult;
};

export default function TranscriptionSettingsSection({ settings }: Props) {
  const { t } = useI18n();

  return (
    <div className="vsSettingsCard vsTranscriptionSection">
      <div className="vsCardSection">
        <h3 className="vsCardSubTitle">{t("存储与离线文稿分发", "Storage & Off-line File Hosting")}</h3>
        <label className="vsField">
          <span className="vsFieldLabel">{t("文件上传模式", "Upload Mode")}</span>
          <select
            data-testid="transcription-upload-mode"
            className="vsSelect"
            value={settings.transcriptionUploadMode}
            onChange={(e) => settings.onTranscriptionUploadModeChange(e.target.value)}
          >
            <option value="static">{t("本地静态发布 (Static)", "Local static hosting")}</option>
            <option value="s3">{t("S3 兼容对象存储 (S3 API)", "S3-compatible object storage")}</option>
            <option value="disabled">{t("禁用公网分发 (Disabled)", "Disable public distribution")}</option>
          </select>
          <span className="vsFieldHint">{t("控制生成的录音/视频文稿文件如何暂存于存储中供后端模型拉取及分享使用。", "Controls how generated recording/video transcript files are staged for backend model access and sharing.")}</span>
        </label>
        <label className="vsField">
          <span className="vsFieldLabel">{t("分发基础域名 (Public Base URL)", "Public Base URL")}</span>
          <input
            className="vsInput"
            value={settings.transcriptionPublicBaseUrl}
            onChange={(e) => settings.onTranscriptionPublicBaseUrlChange(e.target.value)}
            placeholder="https://files.example.com"
          />
          <span className="vsFieldHint">{t("文件上传结束后生成的访问根锚点。", "Root URL used to access uploaded files.")}</span>
        </label>
      </div>

      {settings.transcriptionUploadMode === "s3" && (
        <div className="vsCardSection border-top">
          <h3 className="vsCardSubTitle">{t("S3 Bucket 连接参数", "S3 Bucket Connection")}</h3>
          <div className="vsFormRow">
            <label className="vsField">
              <span className="vsFieldLabel">Bucket Name</span>
              <input
                className="vsInput"
                value={settings.transcriptionS3Bucket}
                onChange={(e) => settings.onTranscriptionS3BucketChange(e.target.value)}
                placeholder={t("例如: echo-assets", "For example: echo-assets")}
              />
            </label>
            <label className="vsField">
              <span className="vsFieldLabel">{t("Region (区域代码)", "Region")}</span>
              <input
                className="vsInput"
                value={settings.transcriptionS3Region}
                onChange={(e) => settings.onTranscriptionS3RegionChange(e.target.value)}
                placeholder={t("例如: us-east-1", "For example: us-east-1")}
              />
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
            </label>
            <label className="vsField">
              <span className="vsFieldLabel">{t("存储前缀 (Key Prefix)", "Key Prefix")}</span>
              <input
                className="vsInput"
                value={settings.transcriptionS3KeyPrefix}
                onChange={(e) => settings.onTranscriptionS3KeyPrefixChange(e.target.value)}
                placeholder={t("例如: voice-jobs/", "For example: voice-jobs/")}
              />
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
            </label>
          </div>
        </div>
      )}
    </div>
  );
}
