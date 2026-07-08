/**
 * 답변 토큰이 오기 전(preparing) 동안 보여주는 대기 표시.
 *  - 활성 테마(마지막 status 이벤트의 theme, 없으면 generic) 풀에서 멘트를 표시
 *  - 5초마다 직전 멘트를 제외하고 랜덤 교체 (fade in/out 전환)
 *  - status 이벤트가 오면 즉시 그 테마 멘트로 갱신 + 아래에 실제 진행 라벨 표시
 */
import { useEffect, useRef, useState } from "react";
import type { ToolStatus } from "../api";
import { pickMessage } from "../waitingMessages";

const ROTATE_MS = 5000;
const FADE_MS = 300;

interface Props {
  status?: Pick<ToolStatus, "label" | "theme">;
}

export default function WaitingIndicator({ status }: Props) {
  const theme = status?.theme ?? "generic";
  const [message, setMessage] = useState(() => pickMessage(theme));
  const [fading, setFading] = useState(false);
  const messageRef = useRef(message);
  messageRef.current = message;
  const fadeTimerRef = useRef<number | undefined>(undefined);
  const mountedRef = useRef(false);

  /** 직전 멘트를 제외한 새 멘트로 부드럽게(fade) 교체 */
  function swapMessage(nextTheme: string) {
    setFading(true);
    window.clearTimeout(fadeTimerRef.current);
    fadeTimerRef.current = window.setTimeout(() => {
      setMessage(pickMessage(nextTheme, messageRef.current));
      setFading(false);
    }, FADE_MS);
  }

  // 테마가 바뀌면(= 새 status 이벤트) 즉시 그 테마 멘트로 전환
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true; // 최초 마운트는 useState 초기값이 이미 처리
      return;
    }
    swapMessage(theme);
  }, [theme]);

  // 5초마다 랜덤 교체 — 테마가 바뀌면 타이머도 새로 시작
  useEffect(() => {
    const id = window.setInterval(() => swapMessage(theme), ROTATE_MS);
    return () => window.clearInterval(id);
  }, [theme]);

  useEffect(() => () => window.clearTimeout(fadeTimerRef.current), []);

  return (
    <div className="waiting-indicator">
      <div className="waiting-line">
        <span className={`waiting-message ${fading ? "fading" : ""}`}>{message}</span>
        <span className="waiting-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </div>
      {status?.label && <div className="waiting-tool-label">{status.label}</div>}
    </div>
  );
}
