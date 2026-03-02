import { api, type ChatMessage, type ToolCallRecord } from "./api";

export interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallRecord[];
  isLoading?: boolean;
}

type Listener = () => void;

let messages: DisplayMessage[] = [];
let loading = false;
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach((l) => l());
}

export function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getMessages() {
  return messages;
}

export function isLoading() {
  return loading;
}

export async function sendMessage(text: string) {
  if (!text.trim() || loading) return;

  const userMsg: DisplayMessage = { role: "user", content: text };
  messages = [...messages, userMsg, { role: "assistant", content: "", isLoading: true }];
  loading = true;
  notify();

  try {
    const chatHistory: ChatMessage[] = messages
      .filter((m) => !m.isLoading)
      .map((m) => ({ role: m.role, content: m.content }));

    const resp = await api.chat(chatHistory);

    messages = [
      ...messages.slice(0, -1),
      { role: "assistant", content: resp.response, toolCalls: resp.tool_calls },
    ];
  } catch (err) {
    messages = [
      ...messages.slice(0, -1),
      {
        role: "assistant",
        content: `**Error:** ${err instanceof Error ? err.message : "Unknown error"}. Check the API server is running.`,
      },
    ];
  } finally {
    loading = false;
    notify();
  }
}
