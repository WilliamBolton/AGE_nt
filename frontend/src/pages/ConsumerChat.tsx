import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, Wrench, AlertCircle } from "lucide-react";
import { api, type ChatMessage, type ToolCallRecord } from "../lib/api";
import { hasApiKey } from "../lib/settings";

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallRecord[];
  isLoading?: boolean;
}

export default function ConsumerChat() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    if (!hasApiKey()) {
      setMessages((prev) => [
        ...prev,
        { role: "user", content: input },
        {
          role: "assistant",
          content:
            "Please set your Gemini API key in Settings before chatting. Click the Settings button in the sidebar.",
        },
      ]);
      setInput("");
      return;
    }

    const userMsg: DisplayMessage = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg, { role: "assistant", content: "", isLoading: true }]);
    setInput("");
    setLoading(true);

    try {
      const chatHistory: ChatMessage[] = [
        ...messages
          .filter((m) => !m.isLoading)
          .map((m) => ({ role: m.role, content: m.content })),
        { role: "user" as const, content: input },
      ];

      const resp = await api.chat(chatHistory);

      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: "assistant",
          content: resp.response,
          toolCalls: resp.tool_calls,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Unknown error"}. Check your API key in Settings.`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-outline-variant bg-surface-container-lowest px-6 py-4">
        <h2 className="text-lg font-semibold font-heading text-on-surface">Evidence Chat</h2>
        <p className="text-sm text-on-surface-variant">
          Ask questions about aging interventions. Powered by Gemini + AGE-nt evidence database.
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-on-surface-variant space-y-4">
            <Bot size={48} className="text-primary" />
            <div className="text-center space-y-2">
              <p className="text-lg font-medium font-heading text-on-surface">Welcome to AGE-nt</p>
              <p className="text-sm max-w-md">
                Ask about any aging intervention. I have access to evidence data from PubMed,
                clinical trials, patents, grants, news, and more.
              </p>
              <div className="flex flex-wrap gap-2 justify-center mt-4">
                {[
                  "What do we know about rapamycin?",
                  "Compare metformin and NMN evidence",
                  "Which interventions have the most RCTs?",
                  "What are the evidence gaps for senolytics?",
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => setInput(q)}
                    className="px-3 py-1.5 bg-surface-container-lowest border border-outline-variant rounded-full text-xs text-on-surface-variant hover:bg-surface-container hover:border-outline transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            {msg.role === "assistant" && (
              <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center shrink-0">
                <Bot size={16} className="text-on-primary-container" />
              </div>
            )}

            <div
              className={`max-w-[70%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-surface-container-high text-on-surface"
                  : "bg-primary-container text-on-primary-container"
              }`}
            >
              {msg.isLoading ? (
                <div className="flex gap-1.5 py-1">
                  <div className="w-2 h-2 bg-on-primary-container/40 rounded-full animate-bounce" />
                  <div className="w-2 h-2 bg-on-primary-container/40 rounded-full animate-bounce [animation-delay:150ms]" />
                  <div className="w-2 h-2 bg-on-primary-container/40 rounded-full animate-bounce [animation-delay:300ms]" />
                </div>
              ) : (
                <>
                  {/* Tool call badges */}
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {msg.toolCalls.map((tc, j) => (
                        <span
                          key={j}
                          className="inline-flex items-center gap-1 px-2 py-0.5 bg-tertiary-container text-on-tertiary-container rounded-full text-xs"
                        >
                          <Wrench size={10} />
                          {tc.name}
                          {tc.args.intervention && (
                            <span className="opacity-70">({tc.args.intervention})</span>
                          )}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
                </>
              )}
            </div>

            {msg.role === "user" && (
              <div className="w-8 h-8 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0">
                <User size={16} className="text-on-surface-variant" />
              </div>
            )}
          </div>
        ))}
        <div ref={scrollRef} />
      </div>

      {/* Input */}
      <div className="border-t border-outline-variant bg-surface-container-lowest px-6 py-4">
        {!hasApiKey() && (
          <div className="flex items-center gap-2 mb-3 px-3 py-2 bg-error-container text-on-error-container rounded-lg text-xs">
            <AlertCircle size={14} />
            Set your Gemini API key in Settings to start chatting.
          </div>
        )}
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="Ask about an aging intervention..."
            className="flex-1 px-4 py-2.5 border border-outline-variant rounded-xl text-sm bg-surface text-on-surface focus:ring-2 focus:ring-primary focus:border-primary outline-none"
            disabled={loading}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="px-4 py-2.5 bg-primary text-on-primary rounded-xl hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
