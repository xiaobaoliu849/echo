import { useState, useRef, useCallback, useEffect } from "react";
import { streamCanvasGenerate } from "../api";
import { CanvasMessage } from "../types";
import { createMessageId } from "../utils/messageId";
import { createInlineTranslator, type UiLanguage } from "../i18n";

type Mode = "react" | "html";
type View = "preview" | "code";

interface UseCanvasOptions {
  language?: UiLanguage;
}

export default function useCanvas({ language = "zh-CN" }: UseCanvasOptions = {}) {
  const t = createInlineTranslator(language);
  const [messages, setMessages] = useState<CanvasMessage[]>([]);
  const [currentCode, setCurrentCode] = useState("");
  const [codeHistory, setCodeHistory] = useState<string[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [thinkingContent, setThinkingContent] = useState("");
  const [mode, setMode] = useState<Mode>("react");
  const [activeView, setActiveView] = useState<View>("preview");
  const [error, setError] = useState("");

  const streamAbortRef = useRef<AbortController | null>(null);

  const abortActiveStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort();
      streamAbortRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => abortActiveStream();
  }, [abortActiveStream]);

  const pushCodeHistory = useCallback((newCode: string) => {
    setCodeHistory((prev) => {
      const next = [...prev, newCode];
      if (next.length > 20) return next.slice(next.length - 20);
      return next;
    });
    setCurrentCode(newCode);
  }, []);

  const undo = useCallback(() => {
    setCodeHistory((prev) => {
      if (prev.length <= 1) {
        setCurrentCode("");
        return [];
      }
      const next = prev.slice(0, -1);
      setCurrentCode(next[next.length - 1]);
      return next;
    });
  }, []);

  const clearCanvas = useCallback(() => {
    abortActiveStream();
    setMessages([]);
    setCurrentCode("");
    setCodeHistory([]);
    setIsGenerating(false);
    setThinkingContent("");
    setError("");
  }, [abortActiveStream]);

  const generate = async (prompt: string, images?: string[], existingCode?: string) => {
    abortActiveStream();
    const controller = new AbortController();
    streamAbortRef.current = controller;

    setError("");
    setIsGenerating(true);
    setThinkingContent("");
    
    const userMsg: CanvasMessage = {
      id: createMessageId(),
      role: "user",
      content: prompt,
      images,
      timestamp: Date.now()
    };
    
    setMessages((prev) => [...prev, userMsg, {
      id: createMessageId(),
      role: "assistant",
      content: "",
      timestamp: Date.now()
    }]);

    try {
      let codeBuffer = "";
      
      await streamCanvasGenerate(
        {
          prompt,
          images,
          existing_code: existingCode,
          mode
        },
        {
          onDelta: (chunk) => {
            codeBuffer += chunk;
            setCurrentCode(codeBuffer);
            setMessages((prev) => {
              if (prev.length === 0) return prev;
              const next = [...prev];
              const last = next[next.length - 1];
              if (last.role === "assistant") {
                next[next.length - 1] = { ...last, content: codeBuffer };
              }
              return next;
            });
          },
          onReasoning: (chunk) => {
            setThinkingContent((prev) => prev + chunk);
          }
        },
        { signal: controller.signal }
      );
      
      pushCodeHistory(codeBuffer);
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const next = [...prev];
        const last = next[next.length - 1];
        if (last.role === "assistant") {
          next[next.length - 1] = { ...last, codeSnapshot: codeBuffer };
        }
        return next;
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      setError(err instanceof Error ? err.message : t("生成失败", "Generation failed"));
      setMessages((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (last.role === "assistant" && !last.content.trim()) {
          return prev.slice(0, -1);
        }
        return prev;
      });
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
        setIsGenerating(false);
      }
    }
  };

  const generateFromPrompt = useCallback((prompt: string, images?: string[]) => {
    generate(prompt, images);
  }, [mode, abortActiveStream, pushCodeHistory]);

  const reviseCode = useCallback((instruction: string) => {
    generate(instruction, undefined, currentCode);
  }, [currentCode, mode, abortActiveStream, pushCodeHistory]);

  return {
    messages,
    currentCode,
    codeHistory,
    isGenerating,
    thinkingContent,
    mode,
    activeView,
    error,
    generateFromPrompt,
    reviseCode,
    undo,
    clearCanvas,
    setMode,
    setActiveView
  };
}
