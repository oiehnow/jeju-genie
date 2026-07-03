/**
 * 채팅 영역 좌측의 플로팅 마스코트 — 챗 상태에 따라 포즈가 바뀐다.
 *   idle      : mascot_1.png      (평상시)
 *   thinking  : mascot_think.png  (질문을 받고 대답 준비 중 — 첫 토큰 전)
 *   answering : mascot_answer.png (대답 스트리밍 중)
 * 세 이미지를 모두 렌더하고 opacity만 토글해 전환 시 로딩 깜빡임을 없앤다.
 * 위아래 float 애니메이션은 항상 유지, thinking/answering 에서는 빨라진다.
 */
import mascotIdle from "../assets/mascot_1.png";
import mascotThink from "../assets/mascot_think.png";
import mascotAnswer from "../assets/mascot_answer.png";

export type MascotState = "idle" | "thinking" | "answering";

const IMAGES: Record<MascotState, string> = {
  idle: mascotIdle,
  thinking: mascotThink,
  answering: mascotAnswer,
};

interface Props {
  state: MascotState;
}

export default function FloatingMascot({ state }: Props) {
  return (
    <div
      className={`floating-mascot ${state !== "idle" ? "talking" : ""}`}
      aria-hidden="true"
    >
      {(Object.keys(IMAGES) as MascotState[]).map((key) => (
        <img
          key={key}
          src={IMAGES[key]}
          alt=""
          className={state === key ? "active" : ""}
        />
      ))}
    </div>
  );
}
