import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
import { LiveAvatarPlayback, type AvatarFrame } from "../utils/liveAvatarPlayback";

export default function LiveAvatarPlayer({ stream }: { stream: EventTarget }) {
  const { t } = useI18n();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<"waiting" | "playing" | "error">("waiting");
  const [image, setImage] = useState("");
  useEffect(() => {
    if (!videoRef.current) return;
    const player = new LiveAvatarPlayback(videoRef.current, (error) => setStatus(error ? "error" : "playing"));
    const reset = () => { player.reset(); setImage(""); setStatus("waiting"); };
    const interrupt = () => { player.reset(true); setImage(""); setStatus("waiting"); };
    const frame = (event: Event) => {
      const data = (event as MessageEvent<AvatarFrame>).data;
      if (/^image\/(jpeg|png|webp)$/.test(data.mimeType)) {
        setImage(`data:${data.mimeType};base64,${data.data}`);
        setStatus("playing");
      } else {
        setImage("");
        player.append(data);
      }
    };
    stream.addEventListener("frame", frame);
    stream.addEventListener("reset", reset);
    stream.addEventListener("interrupt", interrupt);
    return () => { stream.removeEventListener("frame", frame); stream.removeEventListener("reset", reset); stream.removeEventListener("interrupt", interrupt); player.reset(); };
  }, [stream]);
  return <div className="vsLiveAvatarPlayer">
    <video ref={videoRef} autoPlay playsInline controls hidden={Boolean(image) || status === "waiting"}
      aria-label={t("Gemini 实时视频分身", "Gemini Live Avatar")} onError={() => setStatus("error")} />
    {image && <img src={image} alt={t("Gemini 实时视频分身", "Gemini Live Avatar")} />}
    {status !== "playing" && <p role="status">{status === "error"
      ? t("请点击播放；如果仍无法播放，请使用支持 MP4 流的桌面环境或浏览器。", "Click Play. If playback still fails, use a desktop runtime or browser supporting MP4 streaming.")
      : t("通话开始后，分身视频会显示在这里。", "Avatar video will appear here when the conversation starts.")}</p>}
  </div>;
}
