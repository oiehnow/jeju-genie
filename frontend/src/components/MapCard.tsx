/**
 * 답변 말풍선 안에 들어가는 지도 카드 (map SSE 이벤트 수신 시).
 *  - OSM 타일 + attribution, 포인트마다 마커/이름 팝업
 *  - 포인트가 여러 개면 전체가 보이도록 bounds 맞춤
 *  - vite에서 leaflet 기본 마커 png 경로가 깨지므로 divIcon(CSS 핀)으로 대체
 */
import { useEffect } from "react";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "../mapcard.css";
import type { MapPoint } from "../api";

const pinIcon = L.divIcon({
  className: "map-pin-anchor",
  html: '<span class="map-pin"></span>',
  iconSize: [24, 30],
  iconAnchor: [12, 28],
  popupAnchor: [0, -26],
});

/** 포인트 목록에 맞춰 화면을 이동/줌 (여러 개면 bounds, 하나면 setView) */
function FitToPoints({ points }: { points: MapPoint[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView([points[0].lat, points[0].lng], 13);
    } else {
      const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lng] as [number, number]));
      /* 포인트가 많아도 핀이 가장자리에 붙지 않게 패딩 넉넉히, 과도한 줌인 방지 */
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 14 });
    }
  }, [map, points]);
  return null;
}

export default function MapCard({ points }: { points: MapPoint[] }) {
  if (points.length === 0) return null;
  return (
    <div className="map-embed">
      <div className="map-embed-header">
        <span className="map-embed-pin" aria-hidden="true" />
        <span className="map-embed-title">지도로 보기</span>
        <span className="map-embed-count">{points.length}곳</span>
      </div>
      <div className="map-embed-body">
        <MapContainer
          center={[points[0].lat, points[0].lng]}
          zoom={12}
          scrollWheelZoom={false}
          style={{ height: "100%", width: "100%" }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors'
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {points.map((p, i) => (
            <Marker key={`${p.name}-${i}`} position={[p.lat, p.lng]} icon={pinIcon}>
              <Popup>{p.name}</Popup>
            </Marker>
          ))}
          <FitToPoints points={points} />
        </MapContainer>
      </div>
    </div>
  );
}
