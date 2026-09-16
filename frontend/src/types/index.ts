export interface CanvasMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  images?: string[];
  timestamp: number;
  codeSnapshot?: string;
}
