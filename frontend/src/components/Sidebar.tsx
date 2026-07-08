/**
 * 좌측 사이드바 — 둥근 카드형 메뉴 (데스크톱 상시 / 모바일 오버레이).
 *  - 새 대화 / 추천 코스(프리셋 질문 전송) / 실시간 정보(/api/live/summary 패널 토글)
 *  - 즐겨찾기 · 로그인은 데모용 비활성 장식
 *  - 하단 "오늘의 제주 한 컷" 카드 (mascot_2)
 */
import type { LiveSummaryItem } from "../api";
import mascot2 from "../assets/mascot_2.png";

interface Props {
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
  onPresetCourse: () => void;
  busy: boolean;
  liveOpen: boolean;
  liveLoading: boolean;
  liveItems: LiveSummaryItem[];
  onToggleLive: () => void;
}

export default function Sidebar({
  open,
  onClose,
  onNewChat,
  onPresetCourse,
  busy,
  liveOpen,
  liveLoading,
  liveItems,
  onToggleLive,
}: Props) {
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <nav className="side-menu" aria-label="메뉴">
        <button
          type="button"
          className="side-item"
          onClick={() => {
            onNewChat();
            onClose();
          }}
        >
          새 대화
        </button>
        <button
          type="button"
          className="side-item"
          disabled={busy}
          onClick={() => {
            onPresetCourse();
            onClose();
          }}
        >
          추천 코스
        </button>
        <button
          type="button"
          className={`side-item ${liveOpen ? "active" : ""}`}
          onClick={onToggleLive}
        >
          실시간 정보
        </button>
        {liveOpen && (
          <div className="live-panel">
            {liveLoading ? (
              <div className="live-panel-note">실시간 정보를 불러오는 중…</div>
            ) : liveItems.length === 0 ? (
              <div className="live-panel-note">지금은 실시간 정보를 불러올 수 없어요.</div>
            ) : (
              liveItems.map((item, i) => (
                <div key={i} className="live-panel-item">
                  <span className="live-panel-label">{item.label}</span>
                  <span className="live-panel-text">{item.text}</span>
                </div>
              ))
            )}
          </div>
        )}
        <button type="button" className="side-item decor" aria-disabled="true" tabIndex={-1}>
          즐겨찾기
        </button>
        <button type="button" className="side-item decor" aria-disabled="true" tabIndex={-1}>
          로그인 / 회원가입
        </button>
      </nav>

      <div className="jeju-card">
        <img src={mascot2} alt="제주 지니 마스코트" />
        <p className="jeju-card-title">오늘의 제주 한 컷</p>
        <p className="jeju-card-text">바람 좋은 날, 돌담 너머로 바다가 반짝여요.</p>
      </div>
    </aside>
  );
}
