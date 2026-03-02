import { useState, useRef, useEffect, useSyncExternalStore } from "react";
import { Send, Bot, User, Wrench, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { type ToolCallRecord } from "../lib/api";
import {
  subscribe,
  getMessages,
  isLoading,
  sendMessage as storeSend,
} from "../lib/chatStore";

/* ── Markdown prose styles applied inside assistant bubbles ─────────────── */

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      components={{
        h1: ({ children }) => <h1 className="text-lg font-bold mt-4 mb-2 font-heading">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-bold mt-3 mb-1.5 font-heading">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-bold mt-2.5 mb-1 font-heading">{children}</h3>,
        p: ({ children }) => <p className="mb-2 leading-relaxed">{children}</p>,
        ul: ({ children }) => <ul className="list-disc ml-4 mb-2 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal ml-4 mb-2 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        code: ({ children, className }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) {
            return (
              <pre className="bg-black/10 rounded-lg p-3 my-2 overflow-x-auto text-xs">
                <code>{children}</code>
              </pre>
            );
          }
          return <code className="bg-black/10 px-1 py-0.5 rounded text-xs font-mono">{children}</code>;
        },
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-on-primary-container/30 pl-3 italic my-2 opacity-80">
            {children}
          </blockquote>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-2">
            <table className="text-xs border-collapse w-full">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border border-on-primary-container/20 px-2 py-1 text-left font-semibold bg-black/5">{children}</th>,
        td: ({ children }) => <td className="border border-on-primary-container/20 px-2 py-1">{children}</td>,
        hr: () => <hr className="border-on-primary-container/20 my-3" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

/* ── Tool call badge with expandable preview ───────────────────────────── */

function ToolBadge({ tc }: { tc: ToolCallRecord }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="inline-flex items-center gap-1 px-2 py-0.5 bg-tertiary-container text-on-tertiary-container rounded-full text-xs hover:opacity-80 transition-opacity cursor-pointer"
      >
        <Wrench size={10} />
        {tc.name}
        {tc.args.intervention && (
          <span className="opacity-70">({tc.args.intervention})</span>
        )}
      </button>
      {expanded && tc.result_preview && (
        <div className="mt-1 ml-2 p-2 bg-black/5 rounded-lg text-xs font-mono max-h-32 overflow-y-auto whitespace-pre-wrap break-all">
          {tc.result_preview}
        </div>
      )}
    </div>
  );
}

/* ── Main component ────────────────────────────────────────────────────── */

export default function ConsumerChat() {
  const messages = useSyncExternalStore(subscribe, getMessages);
  const loading = useSyncExternalStore(subscribe, isLoading);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = (directText?: string) => {
    const text = directText || input;
    if (!text.trim() || loading) return;
    setInput("");
    storeSend(text);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-outline-variant bg-surface-container-lowest px-6 py-4">
        <h2 className="text-lg font-semibold font-heading text-on-surface">Chat</h2>
        <p className="text-sm text-on-surface-variant">
          Ask questions about aging interventions. Powered by Gemini & AGE-nt.
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-on-surface-variant space-y-4">
            <Bot size={48} className="text-primary" />
            <div className="text-center space-y-2">
              <p className="text-lg font-medium font-heading text-on-surface">Welcome to AGE-nt</p>
              <div className="flex flex-wrap gap-2 justify-center mt-4">
                {[
                  "What do we know about rapamycin?",
                  "Compare metformin and NMN evidence",
                  "Which interventions have the most RCTs?",
                  "What are the evidence gaps for senolytics?",
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => sendMessage(q)}
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
              <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center shrink-0 mt-1">
                <Bot size={16} className="text-on-primary-container" />
              </div>
            )}

            <div
              className={`max-w-[75%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-surface-container-high text-on-surface"
                  : "bg-primary-container text-on-primary-container"
              }`}
            >
              {msg.isLoading ? (
                <div className="flex items-center gap-2 py-1 text-sm">
                  <Loader2 size={14} className="animate-spin" />
                  <span className="opacity-70">Analysing with AGE-nt tools...</span>
                </div>
              ) : (
                <>
                  {/* Tool call badges */}
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-3 pb-2 border-b border-on-primary-container/15">
                      <span className="text-xs opacity-60 mr-1 self-center">Tools used:</span>
                      {msg.toolCalls.map((tc, j) => (
                        <ToolBadge key={j} tc={tc} />
                      ))}
                    </div>
                  )}
                  {/* Markdown-rendered content */}
                  <div className="text-sm">
                    <AssistantMarkdown content={msg.content} />
                  </div>
                </>
              )}
            </div>

            {msg.role === "user" && (
              <div className="w-8 h-8 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0 mt-1">
                <User size={16} className="text-on-surface-variant" />
              </div>
            )}
          </div>
        ))}
        <div ref={scrollRef} />
      </div>

      {/* Input */}
      <div className="border-t border-outline-variant bg-surface-container-lowest px-6 py-4">
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
            onClick={() => sendMessage()}
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
