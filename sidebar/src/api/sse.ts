const BASE = import.meta.env.VITE_API_BASE || "";

export type SseEvent = {
  id?: string;
  event: string;
  data: unknown;
};

export type SseOptions = {
  url: string;
  body: unknown;
  token: string | null;
  lastEventId?: string;
  signal: AbortSignal;
  onEvent: (evt: SseEvent) => void;
  onRetryWait?: (delayMs: number) => void;
  isTerminal: (event: string) => boolean;
};

const BACKOFF_START = 1000;
const BACKOFF_MAX = 30000;

function parseData(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function emitBlock(raw: string, onEvent: (evt: SseEvent) => void): void {
  const lines = raw.split("\n");
  let id: string | undefined;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    const sep = line.indexOf(":");
    const field = sep >= 0 ? line.slice(0, sep) : line;
    let value = sep >= 0 ? line.slice(sep + 1) : "";
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
  }
  if (!id && dataLines.length === 0 && event === "message") return;
  onEvent({
    id,
    event,
    data: parseData(dataLines.join("\n")),
  });
}

export async function readSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (evt: SseEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let idx = buf.indexOf("\n\n");
      while (idx >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        emitBlock(block, onEvent);
        idx = buf.indexOf("\n\n");
      }
    }
    if (buf.trim()) emitBlock(buf, onEvent);
  } finally {
    reader.releaseLock();
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = window.setTimeout(resolve, ms);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * POST SSE：指数退避重连（1s/2s/4s…上限 30s），重连带 Last-Event-ID。
 * 收到终端事件（done / error）后停止。
 */
export async function postSseWithReconnect(opts: SseOptions): Promise<void> {
  let delay = BACKOFF_START;
  let lastEventId = opts.lastEventId;
  let terminal = false;
  let seq = 0;

  while (!opts.signal.aborted && !terminal) {
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      };
      if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
      if (lastEventId) headers["Last-Event-ID"] = lastEventId;

      const res = await fetch(`${BASE}${opts.url}`, {
        method: "POST",
        headers,
        body: JSON.stringify(opts.body),
        signal: opts.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`SSE HTTP ${res.status}`);
      }

      await readSseStream(
        res.body,
        (evt) => {
          seq += 1;
          lastEventId = evt.id || String(seq);
          if (opts.isTerminal(evt.event)) terminal = true;
          opts.onEvent({ ...evt, id: lastEventId });
        },
        opts.signal,
      );

      if (terminal || opts.signal.aborted) return;
      throw new Error("SSE 提前结束");
    } catch (err) {
      if (opts.signal.aborted || terminal) return;
      if (err instanceof DOMException && err.name === "AbortError") return;
      opts.onRetryWait?.(delay);
      try {
        await sleep(delay, opts.signal);
      } catch {
        return;
      }
      delay = Math.min(delay * 2, BACKOFF_MAX);
    }
  }
}
