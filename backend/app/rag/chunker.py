"""단순·견고한 텍스트 청커 — 문단 우선 분할 + 오버랩."""
from app.config import settings


def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            chunks.append(current)
        # 문단 자체가 너무 길면 하드 슬라이스
        while len(para) > chunk_size:
            chunks.append(para[:chunk_size])
            para = para[chunk_size - overlap :]
        current = para
    if current:
        chunks.append(current)

    # 오버랩: 이전 청크 꼬리를 다음 청크 머리에 붙여 문맥 단절 완화
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            overlapped.append(prev[-overlap:] + "\n" + cur)
        return overlapped
    return chunks
