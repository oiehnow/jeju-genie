import type { Source } from "../api";

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  streaming?: boolean;
}

/** 말풍선 — 지니(왼쪽, 꼬리 달린 흰 풍선) / 사용자(오른쪽, 파란 풍선) */
export default function MessageBubble({ msg }: { msg: Message }) {
  const isGenie = msg.role === "assistant";
  return (
    <div className={`bubble-row ${isGenie ? "genie" : "user"}`}>
      <div className={`bubble ${isGenie ? "genie" : "user"}`}>
        <div className="bubble-text">
          {msg.content}
          {msg.streaming && <span className="cursor">▍</span>}
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
