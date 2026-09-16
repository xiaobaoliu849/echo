import { useState, useRef, KeyboardEvent, ChangeEvent } from "react";
import { Send, Image as ImageIcon, X } from "lucide-react";

interface CanvasPromptBarProps {
  onSubmit: (prompt: string, images: string[]) => void;
  isGenerating: boolean;
  placeholder: string;
}

export default function CanvasPromptBar({ onSubmit, isGenerating, placeholder }: CanvasPromptBarProps) {
  const [prompt, setPrompt] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = () => {
    if ((prompt.trim() || images.length > 0) && !isGenerating) {
      onSubmit(prompt, images);
      setPrompt("");
      setImages([]);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image") !== -1) {
        const blob = items[i].getAsFile();
        if (blob) {
          const reader = new FileReader();
          reader.onload = (ev) => {
            if (ev.target?.result) {
              setImages((prev) => [...prev, ev.target!.result as string]);
            }
          };
          reader.readAsDataURL(blob);
        }
      }
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) {
      Array.from(files).forEach((file) => {
        if (file.type.startsWith("image/")) {
          const reader = new FileReader();
          reader.onload = (ev) => {
            if (ev.target?.result) {
              setImages((prev) => [...prev, ev.target!.result as string]);
            }
          };
          reader.readAsDataURL(file);
        }
      });
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const removeImage = (index: number) => {
    setImages((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div className="vsCanvasPromptBar" style={{ display: "flex", flexDirection: "column", gap: "8px", padding: "12px", background: "var(--bg-card)", borderTop: "1px solid var(--border-color)" }}>
      {images.length > 0 && (
        <div className="vsCanvasImageStrip" style={{ display: "flex", gap: "8px", overflowX: "auto", paddingBottom: "4px" }}>
          {images.map((img, idx) => (
            <div key={idx} style={{ position: "relative", width: "60px", height: "60px", flexShrink: 0, borderRadius: "6px", overflow: "hidden", border: "1px solid var(--border-color)" }}>
              <img src={img} alt="attachment" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              <button onClick={() => removeImage(idx)} style={{ position: "absolute", top: "2px", right: "2px", background: "rgba(0,0,0,0.5)", color: "white", border: "none", borderRadius: "50%", width: "16px", height: "16px", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
        <button className="vsCanvasAttachBtn" onClick={() => fileInputRef.current?.click()} disabled={isGenerating} style={{ padding: "8px", background: "transparent", border: "none", cursor: "pointer", color: "var(--text-secondary)", borderRadius: "6px" }}>
          <ImageIcon size={20} />
        </button>
        <input type="file" ref={fileInputRef} onChange={handleFileChange} accept="image/*" multiple style={{ display: "none" }} />
        <textarea
          className="vsCanvasPromptInput custom-scrollbar"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={placeholder}
          disabled={isGenerating}
          rows={Math.min(5, Math.max(1, prompt.split("\n").length))}
          style={{ flex: 1, resize: "none", padding: "10px", borderRadius: "8px", border: "1px solid var(--border-color)", background: "var(--bg-primary)", color: "var(--text-primary)", outline: "none", fontFamily: "inherit" }}
        />
        <button className="vsCanvasSendBtn" onClick={handleSubmit} disabled={isGenerating || (!prompt.trim() && images.length === 0)} style={{ padding: "8px 12px", background: "var(--brand)", color: "white", border: "none", borderRadius: "8px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
