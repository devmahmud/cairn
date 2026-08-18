// Network failures are deliberately left uncaught -- the caller distinguishes "bad data" from "dropped, try to resume" by whether this throws.

export interface ParsedSSEFrame {
  id: string | null;
  event: string;
  data: unknown;
}

export interface SSEParseError {
  message: string;
  raw: string;
}

export type SSEStreamItem =
  | { kind: "event"; frame: ParsedSSEFrame }
  | { kind: "parse-error"; error: SSEParseError };

async function* readLines(
  reader: ReadableStreamDefaultReader<Uint8Array>,
): AsyncGenerator<string> {
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      yield line.endsWith("\r") ? line.slice(0, -1) : line;
    }
  }
  buffer += decoder.decode();
  if (buffer.length > 0) {
    yield buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer;
  }
}

export async function* parseSSEStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SSEStreamItem> {
  const reader = body.getReader();
  let dataLines: string[] = [];
  let eventType = "";
  let lastId: string | null = null;

  try {
    for await (const line of readLines(reader)) {
      if (line === "") {
        if (dataLines.length === 0) {
          eventType = "";
          continue;
        }
        const raw = dataLines.join("\n");
        const type = eventType || "message";
        dataLines = [];
        eventType = "";
        try {
          yield { kind: "event", frame: { id: lastId, event: type, data: JSON.parse(raw) } };
        } catch (cause) {
          yield {
            kind: "parse-error",
            error: { message: cause instanceof Error ? cause.message : "Invalid JSON", raw },
          };
        }
        continue;
      }

      if (line.startsWith(":")) continue; // comment / heartbeat, incl. FastAPI's `:ping`

      const colonIdx = line.indexOf(":");
      const field = colonIdx === -1 ? line : line.slice(0, colonIdx);
      let value = colonIdx === -1 ? "" : line.slice(colonIdx + 1);
      if (value.startsWith(" ")) value = value.slice(1);

      if (field === "event") eventType = value;
      else if (field === "data") dataLines.push(value);
      else if (field === "id" && !value.includes("\0")) lastId = value;
      // `retry:` is intentionally ignored -- reconnect policy is driven by the caller.
    }
  } finally {
    reader.releaseLock();
  }
}
