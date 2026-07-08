/**
 * 좌측 사이드바 — 둥근 카드형 메뉴 (데스크톱 상시 / 모바일 오버레이).
 *  - 새 대화
 *  - 추천 코스: 코스 카드 6종 서브패널 → 클릭 시 프리셋 질문을 채팅으로 전송
 *  - 실시간 정보: 유가/날씨/교통 상세 패널(/api/live/detail, 새로고침 지원)
 *    + 외국인 관광객 밀집(메인 영역 오버레이 지도)
 *  - 즐겨찾기 · 로그인은 데모용 비활성 장식
 *  - 하단 "오늘의 제주 뉴스" 카드 (/api/news, 실패 시 숨김)
 */
import { useEffect, useRef, useState } from "react";
import {
  fetchLiveDetail,
  fetchNews,
  type LiveCategory,
  type LiveDetailItem,
  type NewsItem,
} from "../api";
import mascot2 from "../assets/mascot_2.png";

interface Props {
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
  /** 코스 카드 클릭 시 프리셋 질문을 채팅으로 전송 */
  onSend: (text: string) => void;
  busy: boolean;
  /** 외국인 관광객 밀집 지도 오버레이 열기 */
  onOpenDensity: () => void;
}

/** 추천 코스 6종 — 카드 제목 + 한 줄 설명 + 채팅 프리셋 질문 */
const COURSES: { title: string; desc: string; prompt: string }[] = [
  {
    title: "한라산 등반 코스",
    desc: "성판악-백록담-관음사, 왕복 8~9시간",
    prompt:
      "한라산 등반 코스를 짜줘. 성판악/영실 코스 비교, 구간별 소요 시간, 준비물, 입산 예약 방법과 통제 시간까지 포함해서 자세히 알려줘",
  },
  {
    title: "제주도 자전거 한바퀴 코스",
    desc: "환상자전거길 234km, 3~4일 일주",
    prompt:
      "제주도 자전거 한바퀴(환상자전거길 일주) 코스를 짜줘. 일자별 구간 나누기, 숙소 잡기 좋은 거점 마을, 자전거 대여와 인증센터 위치, 주의할 오르막 구간까지 자세히 알려줘",
  },
  {
    title: "제주도 맛집 투어 코스",
    desc: "흑돼지·고기국수·해산물 권역별 동선",
    prompt:
      "제주도 맛집 투어 코스를 짜줘. 흑돼지, 고기국수, 갈치·해산물, 카페 디저트를 제주시/서귀포/동부/서부 권역별 동선으로 묶고, 웨이팅 팁과 예산 감각까지 알려줘",
  },
  {
    title: "우도 관광 코스",
    desc: "성산항 배편으로 떠나는 반나절 섬 일주",
    prompt:
      "우도 관광 코스를 짜줘. 성산항 배편 시간과 요금, 섬 안 이동수단 비교(전기바이크/순환버스/자전거), 검멀레해변·우도봉 같은 필수 스팟 동선, 우도 땅콩 먹거리까지 자세히 알려줘",
  },
  {
    title: "제주도 역사 테마 코스",
    desc: "삼성혈부터 4.3평화공원까지 역사 여행",
    prompt:
      "제주도 역사 테마 코스를 짜줘. 삼성혈, 제주목 관아, 항파두리 항몽유적지, 제주 4.3평화공원을 1~2일 동선으로 묶고 각 장소의 역사적 배경 설명도 곁들여줘",
  },
  {
    title: "제주도 캠핑 테마 코스",
    desc: "해변·숲 캠핑장과 차박 명소 1박 2일",
    prompt:
      "제주도 캠핑 테마 코스를 짜줘. 해변 캠핑장과 숲 캠핑장 추천, 차박 가능한 명소, 예약 방법과 준비물 체크리스트, 1박 2일 일정 예시까지 자세히 알려줘",
  },
];

/** 실시간 정보 상세 카테고리 (밀집 지도는 별도 오버레이) */
const LIVE_CATEGORIES: { key: LiveCategory; label: string }[] = [
  { key: "fuel", label: "유가" },
  { key: "weather", label: "날씨" },
  { key: "traffic", label: "교통" },
];

const CATEGORY_TITLE: Record<LiveCategory, string> = {
  fuel: "제주 유가",
  weather: "제주 날씨",
  traffic: "제주 교통",
};

export default function Sidebar({ open, onClose, onNewChat, onSend, busy, onOpenDensity }: Props) {
  const [courseOpen, setCourseOpen] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);
  const [category, setCategory] = useState<LiveCategory | null>(null);
  const [items, setItems] = useState<LiveDetailItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [news, setNews] = useState<NewsItem[]>([]);
  /** 카테고리 전환/새로고침 연타 시 이전 요청 결과를 버리기 위한 카운터 */
  const reqRef = useRef(0);

  // 뉴스 카드 — 마운트 시 1회, 실패/빈 응답이면 카드 숨김
  useEffect(() => {
    let alive = true;
    fetchNews().then((n) => {
      if (alive) setNews(n.slice(0, 4));
    });
    return () => {
      alive = false;
    };
  }, []);

  function loadDetail(cat: LiveCategory, refresh: boolean) {
    const id = ++reqRef.current;
    setLoading(true);
    fetchLiveDetail(cat, refresh).then((res) => {
      if (reqRef.current !== id) return;
      setItems(res);
      setLoading(false);
    });
  }

  function selectCategory(cat: LiveCategory) {
    if (cat === category) {
      // 같은 카테고리 재클릭 → 패널 접기
      reqRef.current += 1;
      setCategory(null);
      setLoading(false);
      return;
    }
    setCategory(cat);
    setItems([]);
    loadDetail(cat, false);
  }

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
          className={`side-item ${courseOpen ? "active" : ""}`}
          onClick={() => {
            setCourseOpen((v) => !v);
            setLiveOpen(false);
          }}
        >
          추천 코스
        </button>
        {courseOpen && (
          <div className="course-panel">
            {COURSES.map((c) => (
              <button
                key={c.title}
                type="button"
                className="course-card"
                disabled={busy}
                onClick={() => {
                  onSend(c.prompt);
                  setCourseOpen(false);
                  onClose();
                }}
              >
                <span className="course-card-title">{c.title}</span>
                <span className="course-card-desc">{c.desc}</span>
              </button>
            ))}
          </div>
        )}

        <button
          type="button"
          className={`side-item ${liveOpen ? "active" : ""}`}
          onClick={() => {
            setLiveOpen((v) => !v);
            setCourseOpen(false);
          }}
        >
          실시간 정보
        </button>
        {liveOpen && (
          <div className="side-submenu">
            <div className="side-subrow">
              {LIVE_CATEGORIES.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  className={`side-subitem ${category === c.key ? "active" : ""}`}
                  onClick={() => selectCategory(c.key)}
                >
                  {c.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="side-subitem wide"
              onClick={() => {
                onOpenDensity();
                onClose();
              }}
            >
              외국인 관광객 밀집
            </button>

            {category && (
              <div className="live-panel">
                <div className="live-panel-head">
                  <span className="live-panel-title">{CATEGORY_TITLE[category]}</span>
                  <button
                    type="button"
                    className="panel-refresh"
                    disabled={loading}
                    onClick={() => loadDetail(category, true)}
                  >
                    {loading ? <span className="spinner" aria-label="불러오는 중" /> : "새로고침"}
                  </button>
                </div>
                {loading && items.length === 0 ? (
                  <div className="live-panel-note">실시간 정보를 불러오는 중…</div>
                ) : items.length === 0 ? (
                  <div className="live-panel-note">지금은 실시간 정보를 불러올 수 없어요.</div>
                ) : (
                  items.map((item, i) => (
                    <div key={i} className="live-panel-item">
                      <span className="live-panel-label">{item.label}</span>
                      <span className="live-panel-text">{item.text}</span>
                    </div>
                  ))
                )}
              </div>
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

      {news.length > 0 && (
        <div className="jeju-card news-card">
          <div className="news-head">
            <img src={mascot2} alt="제주 지니 마스코트" />
            <p className="jeju-card-title">오늘의 제주 뉴스</p>
          </div>
          <ul className="news-list">
            {news.map((n, i) => (
              <li key={i}>
                <a href={n.url} target="_blank" rel="noreferrer">
                  <span className="news-item-title">{n.title}</span>
                  <span className="news-item-source">{n.source}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}
