import type { LiveSource, Source } from "../api";

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  live?: LiveSource[];
  streaming?: boolean;
}

/** 말풍선 — 지니(왼쪽, 꼬리 달린 흰 풍선) / 사용자(오른쪽, 파란 풍선) */
export default function MessageBubble({ msg }: { msg: Message }) {
  const isGenie = msg.role === "assistant";
  const hasLive = isGenie && msg.live && msg.live.length > 0;
  const preparing = isGenie && msg.streaming && !msg.content;
  return (
    <div className={`bubble-row ${isGenie ? "genie" : "user"}`}>
      <div className={`bubble ${isGenie ? "genie" : "user"}`}>
        {hasLive && (
          <div className="live-row" title="이 답변은 실시간 API로 조회한 데이터를 반영했어요">
            <span className="live-dot" />
            <span className="live-label">실시간 데이터</span>
            {msg.live!.map((l, i) => (
              <span key={i} className="live-chip">
                {l.label}
              </span>
            ))}
          </div>
        )}
        <div className="bubble-text">
          {preparing ? (
            <span className="preparing">
              {hasLive ? "실시간 데이터를 반영하는 중이에요…" : "답변을 준비하고 있어요…"}
            </span>
          ) : (
            msg.content
          )}
          {msg.streaming && msg.content && <span className="cursor">▍</span>}
        </div>
        {isGenie && msg.sources && msg.sources.length > 0 && (
          <div className="source-chips">
            {msg.sources.map((s, i) =>
              s.url ? (
                <a key={i} className="chip" href={s.url} target="_blank" rel="noreferrer">
                  출처: {s.title || s.source}
                </a>
              ) : (
                <span key={i} className="chip">
                  출처: {s.title || s.source}
                </span>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}
