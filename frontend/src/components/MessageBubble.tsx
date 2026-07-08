import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { LiveSource, MapPoint, Source, ToolStatus } from "../api";
import mascotAvatar from "../assets/mascot_1.png";
import MapCard from "./MapCard";
import WaitingIndicator from "./WaitingIndicator";

export interface Message {
  role: "user" | "assistant";
  content: string;
  /** 메시지 생성 시각 (epoch ms) — 날짜 구분선/말풍선 시간 표시용 */
  ts: number;
  sources?: Source[];
  live?: LiveSource[];
  map?: MapPoint[];
  streaming?: boolean;
  /** 스트리밍 중 마지막 status 이벤트 (대기 멘트 테마/진행 라벨) */
  status?: Pick<ToolStatus, "label" | "theme">;
}

/** "오전 10:30" 형식 */
export function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" });
}

/** 말풍선 — 지니(왼쪽, 마스코트 아바타 + 흰 풍선) / 사용자(오른쪽, teal 풍선) */
export default function MessageBubble({ msg }: { msg: Message }) {
  const isGenie = msg.role === "assistant";
  const hasLive = isGenie && msg.live && msg.live.length > 0;
  const preparing = isGenie && msg.streaming && !msg.content;
  const time = msg.streaming ? null : (
    <span className="msg-time">{formatTime(msg.ts)}</span>
  );
  return (
    <div className={`bubble-row ${isGenie ? "genie" : "user"}`}>
      {isGenie && (
        <div className="genie-avatar" aria-hidden="true">
          <img src={mascotAvatar} alt="" />
        </div>
      )}
      {!isGenie && time}
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
            <WaitingIndicator status={msg.status} />
          ) : isGenie ? (
            <div className="markdown-body">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ node: _node, ...props }) => (
                    <a {...props} target="_blank" rel="noreferrer" />
                  ),
                }}
              >
                {msg.content}
              </ReactMarkdown>
            </div>
          ) : (
            msg.content
          )}
          {msg.streaming && msg.content && <span className="cursor">▍</span>}
        </div>
        {isGenie && msg.map && msg.map.length > 0 && <MapCard points={msg.map} />}
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
      {isGenie && time}
    </div>
  );
}
