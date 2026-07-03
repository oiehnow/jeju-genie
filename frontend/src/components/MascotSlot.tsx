/**
 * 헤더 마스코트 — mascot_2.png(흰 배경)를 원형 액자로 표시 (시안 UI.png 반영).
 * 이미지 교체 시 assets 파일만 갈아끼우면 된다. 크기는 theme.css 의 --mascot-size.
 * talking prop: 지니가 대답 중일 때 살짝 통통 튀는 애니메이션.
 */
import mascot2 from "../assets/mascot_2.png";

interface Props {
  talking: boolean;
}

export default function MascotSlot({ talking }: Props) {
  return (
    <div className={`mascot-slot ${talking ? "talking" : ""}`} aria-label="제주 지니 마스코트">
      <img src={mascot2} alt="제주 지니" />
    </div>
  );
}
