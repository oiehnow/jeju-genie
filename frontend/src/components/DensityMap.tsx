/**
 * 실시간 외국인 관광객 밀집 지도 — 메인 영역 위 오버레이 카드.
 *  - /api/live/density의 points를 CircleMarker로 표시 (level 1=빨강 크게 / 2=주황 / 3=노랑)
 *  - 상단: 기준 시점(asof) + 범례 + 새로고침 / 닫기 버튼
 *  - 백엔드 미가동/실패 시 빈 상태 안내만 표시 (지도 자체는 유지)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { fetchDensity, type DensityData } from "../api";

/** 제주도 전체가 보이는 bounds (본섬 + 우도/마라도 여유 포함) */
const JEJU_BOUNDS: [[number, number], [number, number]] = [
  [33.1, 126.08],
  [33.62, 127.0],
];

/** level별 색/크기 — 1이 가장 밀집(빨강, 크게) */
const LEVEL_STYLE: Record<number, { color: string; radius: number; label: string }> = {
  1: { color: "#e5484d", radius: 22, label: "밀집 높음" },
  2: { color: "#ff8a3d", radius: 15, label: "보통" },
  3: { color: "#f5c518", radius: 10, label: "낮음" },
};

export default function DensityMap({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<DensityData | null>(null);
  const [loading, setLoading] = useState(true);
  /** 새로고침 연타/언마운트 시 이전 요청 결과를 버리기 위한 카운터 */
  const reqRef = useRef(0);

  const load = useCallback(() => {
    const id = ++reqRef.current;
    setLoading(true);
    fetchDensity().then((d) => {
      if (reqRef.current !== id) return;
      setData(d);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    load();
    return () => {
      reqRef.current += 1;
    };
  }, [load]);

  const points = data?.points ?? [];

  return (
    <div className="density-overlay" role="dialog" aria-label="외국인 관광객 밀집 지도">
      <div className="density-backdrop" onClick={onClose} />
      <div className="density-card">
        <div className="density-head">
          <div>
            <p className="density-title">외국인 관광객 밀집 지도</p>
            <p className="density-asof">
              {/* asof는 "2026-04 기준" 형태로 옴 — '기준'을 덧붙이지 않는다 */}
              {data?.asof ? `${data.asof} · 외국 카드 사용 내역 기반` : "외국 카드 사용 내역 기반"}
            </p>
          </div>
          <div className="density-actions">
            <button type="button" className="panel-refresh" onClick={load} disabled={loading}>
              {loading ? <span className="spinner" aria-label="불러오는 중" /> : "새로고침"}
            </button>
            <button type="button" className="density-close" onClick={onClose}>
              닫기
            </button>
          </div>
        </div>

        <div className="density-legend">
          {[1, 2, 3].map((lv) => (
            <span key={lv}>
              <i style={{ background: LEVEL_STYLE[lv].color }} />
              {LEVEL_STYLE[lv].label}
            </span>
          ))}
        </div>

        <div className="density-map">
          <MapContainer bounds={JEJU_BOUNDS} scrollWheelZoom style={{ height: "100%", width: "100%" }}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {points.map((p, i) => {
              const s = LEVEL_STYLE[p.level] ?? LEVEL_STYLE[3];
              const caption = `${p.name} — 카드 사용 규모 ${p.value.toLocaleString("ko-KR")}`;
              return (
                <CircleMarker
                  key={`${p.name}-${i}`}
                  center={[p.lat, p.lng]}
                  radius={s.radius}
                  pathOptions={{
                    color: s.color,
                    weight: 1.5,
                    fillColor: s.color,
                    fillOpacity: 0.35,
                  }}
                >
                  <Tooltip>{caption}</Tooltip>
                  <Popup>{caption}</Popup>
                </CircleMarker>
              );
            })}
          </MapContainer>
          {loading && points.length === 0 && (
            <div className="density-map-note">밀집 데이터를 불러오는 중…</div>
          )}
          {!loading && points.length === 0 && (
            <div className="density-map-note">지금은 밀집 데이터를 불러올 수 없어요.</div>
          )}
        </div>
      </div>
    </div>
  );
}
