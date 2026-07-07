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

export interface ChatEvents {
  onToken: (token: string) => void;
  onSources: (sources: Source[]) => void;
  onLive: (live: LiveSource[]) => void;
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
        else if (data.type === "done") events.onDone();
      }
    }
  } catch (err) {
    events.onError(err);
  }
}
