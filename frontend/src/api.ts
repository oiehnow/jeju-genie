// 백엔드 SSE 챗 API 클라이언트

export interface Source {
  title: string;
  source: string;
  url: string;
}

/** 실시간 API로 조회된 도구 (UI '실시간 데이터' 배지용) */
export interface LiveSource {
  name: string;
  label: string;
}

/** 에이전트가 도구 실행을 시작할 때 오는 진행 상태 (대기 멘트 테마 전환용) */
export interface ToolStatus {
  tool: string;
  label: string;
  theme: string;
}

/** 답변에 첨부되는 지도 포인트 (map SSE 이벤트) */
export interface MapPoint {
  name: string;
  lat: number;
  lng: number;
}

export interface ChatEvents {
  onToken: (token: string) => void;
  onSources: (sources: Source[]) => void;
  onLive: (live: LiveSource[]) => void;
  onStatus?: (status: ToolStatus) => void;
  onMap?: (points: MapPoint[]) => void;
  onDone: () => void;
  onError: (err: unknown) => void;
}

export async function streamChat(
  message: string,
  history: { role: string; content: string }[],
  events: ChatEvents,
): Promise<void> {
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = JSON.parse(line.slice(6));
        if (data.type === "token") events.onToken(data.content);
        else if (data.type === "sources") events.onSources(data.sources);
        else if (data.type === "live") events.onLive(data.live);
        else if (data.type === "status")
          events.onStatus?.({ tool: data.tool, label: data.label, theme: data.theme });
        else if (data.type === "map" && Array.isArray(data.points))
          events.onMap?.(data.points);
        else if (data.type === "done") events.onDone();
      }
    }
  } catch (err) {
    events.onError(err);
  }
}

/* ── 보조 REST 엔드포인트 — 백엔드 미구현/실패 시 조용히 무시 ── */

/** 헤더 기온 칩용 현재 날씨. 실패하면 null (칩 숨김). */
export interface NowInfo {
  temp: string | null;
  summary: string;
}

export async function fetchNow(): Promise<NowInfo | null> {
  try {
    const resp = await fetch("/api/now");
    if (!resp.ok) return null;
    const data = await resp.json();
    return { temp: data.temp ?? null, summary: data.summary ?? "" };
  } catch {
    return null;
  }
}

/** 사이드바 '오늘의 제주 뉴스' 카드 항목. 실패하면 빈 배열 (카드 숨김). */
export interface NewsItem {
  title: string;
  url: string;
  source: string;
}

export async function fetchNews(): Promise<NewsItem[]> {
  try {
    const resp = await fetch("/api/news");
    if (!resp.ok) return [];
    const data = await resp.json();
    return Array.isArray(data.items) ? data.items : [];
  } catch {
    return [];
  }
}

/** 사이드바 '실시간 정보' 카테고리 상세 패널. 실패하면 빈 배열. */
export type LiveCategory = "fuel" | "weather" | "traffic";

/** 상세 항목에 딸린 외부 링크 (예: 최저가 주유소 → 카카오맵 검색) */
export interface LiveDetailLink {
  label: string;
  url: string;
  desc?: string;
}

export interface LiveDetailItem {
  label: string;
  text: string;
  links?: LiveDetailLink[];
}

export async function fetchLiveDetail(
  category: LiveCategory,
  refresh = false,
): Promise<LiveDetailItem[]> {
  try {
    const resp = await fetch(`/api/live/detail?category=${category}&refresh=${refresh ? 1 : 0}`);
    if (!resp.ok) return [];
    const data = await resp.json();
    return Array.isArray(data.items) ? data.items : [];
  } catch {
    return [];
  }
}

/** 외국인 관광객 밀집 지도 데이터. 실패하면 null (빈 상태 표시). */
export interface DensityPoint {
  name: string;
  lat: number;
  lng: number;
  value: number;
  level: number; // 1=최다, 2=중간, 3=낮음
}

export interface DensityData {
  asof: string;
  points: DensityPoint[];
}

export async function fetchDensity(): Promise<DensityData | null> {
  try {
    const resp = await fetch("/api/live/density");
    if (!resp.ok) return null;
    const data = await resp.json();
    return {
      asof: typeof data.asof === "string" ? data.asof : "",
      points: Array.isArray(data.points) ? data.points : [],
    };
  } catch {
    return null;
  }
}

/** 답변 완료 후 후속 질문 제안. 실패/빈 응답이면 빈 배열 (칩 미표시). */
export async function fetchSuggestions(question: string, answer: string): Promise<string[]> {
  try {
    const resp = await fetch("/api/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer }),
    });
    if (!resp.ok) return [];
    const data = await resp.json();
    return Array.isArray(data.suggestions) ? data.suggestions : [];
  } catch {
    return [];
  }
}
