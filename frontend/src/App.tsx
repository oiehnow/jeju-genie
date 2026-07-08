import { useEffect, useRef, useState, type ReactElement } from "react";
import {
  fetchNow,
  fetchSuggestions,
  streamChat,
  type LiveSource,
  type MapPoint,
  type NowInfo,
  type Source,
  type ToolStatus,
} from "./api";
import DensityMap from "./components/DensityMap";
import FloatingMascot, { type MascotState } from "./components/FloatingMascot";
import MascotSlot from "./components/MascotSlot";
import MessageBubble, { type Message } from "./components/MessageBubble";
import Sidebar from "./components/Sidebar";
import "./app.css";

const makeWelcome = (): Message => ({
  role: "assistant",
  content: "안녕하세요! 제주에 관한 모든 것을 아는 제주 지니예요. 무엇이 궁금하세요?",
  ts: Date.now(),
});

const SUGGESTIONS = [
  "성산일출봉 가는 법 알려줘",
  "흑돼지 맛집 어디서 찾아?",
  "2박 3일 일정 추천해줘",
  "겨울에 제주 가면 뭐 볼까?",
];

/** 제주 밖 질문 거절 답변 휴리스틱 — sorry 마스코트 표시 여부 */
function isSorryAnswer(answer: string): boolean {
  return answer.includes("자료함에 없") || (answer.includes("죄송") && answer.includes("ㅠㅠ"));
}

/** 날짜 구분선 라벨 — "오늘 · 7월 8일 (수)" / 과거 날짜는 "7월 8일 (수)" */
function formatDateLabel(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  const label = d.toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  });
  return isToday ? `오늘 · ${label}` : label;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([makeWelcome()]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mascotState, setMascotState] = useState<MascotState>("idle");
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [now, setNow] = useState<NowInfo | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [densityOpen, setDensityOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  /** 후속 질문 요청 유효성 — 새 질문/새 대화가 시작되면 이전 요청 결과를 버린다 */
  const suggestReqRef = useRef(0);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, followUps]);

  // 헤더 기온 칩 — 마운트 시 1회, 실패하면 칩 숨김
  useEffect(() => {
    let alive = true;
    fetchNow().then((info) => {
      if (alive) setNow(info);
    });
    return () => {
      alive = false;
    };
  }, []);

  function newChat() {
    if (busy) return;
    suggestReqRef.current += 1;
    setFollowUps([]);
    setMessages([makeWelcome()]);
    setMascotState("idle");
  }

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setMascotState("thinking");
    setInput("");
    setFollowUps([]);
    const reqId = ++suggestReqRef.current;

    const history = messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [
      ...prev,
      { role: "user", content: q, ts: Date.now() },
      { role: "assistant", content: "", ts: Date.now(), streaming: true },
    ]);

    const patchLast = (fn: (m: Message) => Message) =>
      setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])]);

    let answer = "";

    await streamChat(q, history, {
      onToken: (t) => {
        answer += t;
        setMascotState("answering");
        patchLast((m) => ({ ...m, content: m.content + t }));
      },
      onSources: (sources: Source[]) => patchLast((m) => ({ ...m, sources })),
      onLive: (live: LiveSource[]) => patchLast((m) => ({ ...m, live })),
      onMap: (points: MapPoint[]) => patchLast((m) => ({ ...m, map: points })),
      onStatus: (s: ToolStatus) =>
        patchLast((m) => ({ ...m, status: { label: s.label, theme: s.theme } })),
      onDone: () => {
        patchLast((m) => ({ ...m, streaming: false, ts: Date.now() }));
        setBusy(false);
        // 답변 완료 후에는 다음 질문 전까지 answer(또는 거절이면 sorry) 포즈 유지
        setMascotState(isSorryAnswer(answer) ? "sorry" : "answered");
        // 후속 질문 제안 — 비동기, 실패/빈 배열이면 칩 미표시
        if (answer) {
          fetchSuggestions(q, answer).then((s) => {
            if (suggestReqRef.current === reqId) setFollowUps(s);
          });
        }
      },
      onError: () => {
        patchLast((m) => ({
          ...m,
          streaming: false,
          ts: Date.now(),
          content: m.content || "연결에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.",
        }));
        setBusy(false);
        setMascotState("idle");
      },
    });
  }

  // 날짜 구분선을 끼워 넣은 메시지 목록
  const rows: ReactElement[] = [];
  let lastDateKey = "";
  messages.forEach((m, i) => {
    const dateKey = new Date(m.ts).toDateString();
    if (dateKey !== lastDateKey) {
      lastDateKey = dateKey;
      rows.push(
        <div key={`date-${dateKey}`} className="date-divider">
          <span>{formatDateLabel(m.ts)}</span>
        </div>,
      );
    }
    rows.push(<MessageBubble key={i} msg={m} />);
  });

  return (
    <div className="app-shell">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNewChat={newChat}
        onSend={send}
        busy={busy}
        onOpenDensity={() => setDensityOpen(true)}
      />
      {sidebarOpen && (
        <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />
      )}
      {densityOpen && <DensityMap onClose={() => setDensityOpen(false)} />}

      <div className="main">
        <header className="header">
          <button
            type="button"
            className="hamburger"
            aria-label="메뉴 열기"
            onClick={() => setSidebarOpen(true)}
          >
            <span />
            <span />
            <span />
          </button>
          <MascotSlot talking={busy} />
          <div className="header-text">
            <h1>Jeju Genie</h1>
            <p className="header-sub">제주 여행 AI 컨시어지</p>
          </div>
          {now?.temp && (
            <div className="temp-chip" title={now.summary || "현재 제주 기온"}>
              {now.temp}°C
            </div>
          )}
        </header>

        <div className="chat-card">
          <div className="chat-scroll" ref={scrollRef}>
            {rows}
            {messages.length === 1 && (
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
            {!busy && followUps.length > 0 && (
              <div className="followups">
                {followUps.map((s) => (
                  <button key={s} type="button" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
          <FloatingMascot state={mascotState} />
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
        <p className="disclaimer">
          AI가 생성한 답변입니다. 중요한 정보는 공식 홈페이지를 확인해 주세요.
        </p>
      </div>
    </div>
  );
}
