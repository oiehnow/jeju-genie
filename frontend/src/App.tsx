import { useEffect, useRef, useState } from "react";
import { streamChat, type LiveSource, type Source } from "./api";
import FloatingMascot, { type MascotState } from "./components/FloatingMascot";
import MascotSlot from "./components/MascotSlot";
import MessageBubble, { type Message } from "./components/MessageBubble";
import "./app.css";

const WELCOME: Message = {
  role: "assistant",
  content: "안녕하세요! 제주에 관한 모든 것을 아는 제주 지니예요. 무엇이 궁금하세요?",
};

const SUGGESTIONS = [
  "성산일출봉 가는 법 알려줘",
  "흑돼지 맛집 어디서 찾아?",
  "2박 3일 일정 추천해줘",
  "겨울에 제주 가면 뭐 볼까?",
];

export default function App() {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mascotState, setMascotState] = useState<MascotState>("idle");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setMascotState("thinking");
    setInput("");

    const history = messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "", streaming: true },
    ]);

    const patchLast = (fn: (m: Message) => Message) =>
      setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])]);

    await streamChat(q, history, {
      onToken: (t) => {
        setMascotState("answering");
        patchLast((m) => ({ ...m, content: m.content + t }));
      },
      onSources: (sources: Source[]) => patchLast((m) => ({ ...m, sources })),
      onLive: (live: LiveSource[]) => patchLast((m) => ({ ...m, live })),
      onDone: () => {
        patchLast((m) => ({ ...m, streaming: false }));
        setBusy(false);
        setMascotState("idle");
      },
      onError: () => {
        patchLast((m) => ({
          ...m,
          streaming: false,
          content: m.content || "연결에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.",
        }));
        setBusy(false);
        setMascotState("idle");
      },
    });
  }

  return (
    <div className="app">
      <header className="header">
        <MascotSlot talking={busy} />
        <div className="header-text">
          <h1>Jeju Genie</h1>
        </div>
      </header>

      <div className="chat-body">
        <FloatingMascot state={mascotState} />
        <div className="chat-scroll" ref={scrollRef}>
          {messages.map((m, i) => (
            <MessageBubble key={i} msg={m} />
          ))}
          {messages.length === 1 && (
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <form
        className="input-bar"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="제주 지니에게 물어보세요…"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          {busy ? "…" : "보내기"}
        </button>
      </form>
    </div>
  );
}
