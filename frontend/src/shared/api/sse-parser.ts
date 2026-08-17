// Cairn frontend — the SSE wire parser (BLUEPRINT.md §4.2, §8 step 8).
//
// Layer 2 of the pipeline: a spec-compliant async generator over a fetch
// `ReadableStream<Uint8Array>` body -- decode -> buffer -> blank-line
// dispatch -> skip `:`-prefixed comments (FastAPI's native
// `EventSourceResponse` heartbeat pings, §3.7) -> `JSON.parse` the
// accumulated `data:` lines. Framework-agnostic and transport-agnostic: it
// doesn't know about `ChatSSEEvent`, `fetch`, or Zustand -- Layer 3
// (`features/chat/hooks/use-streaming-chat.ts`) is what gives the parsed
// `event`/`data` pairs domain meaning.
//
// A malformed `data:` payload is surfaced as a typed `{ kind: "parse-error"
// }` item, not a silent `console.warn` -- the caller decides whether one bad
// frame is fatal for the stream. A genuine network failure (the connection
// drops mid-read) is deliberately *not* caught here: it propagates as a
// rejected `reader.read()`/thrown error out of this generator, which is
// exactly the signal `use-streaming-chat.ts` needs to tell "the parser saw
// bad data" apart from "the connection dropped, try to resume".
//
// Line splitting only recognizes `\n` and `\r\n` (stripping a trailing `\r`),
// not a lone `\r` -- real SSE servers (this one included, via Starlette/
// uvicorn) never emit CR-only line endings, and handling that third case
// would add real complexity for a wire format nothing here produces.

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
      // `retry:` (reconnection-time hint) is intentionally ignored -- this
      // template's reconnect policy (§4.2) is driven by the caller, not the
      // server-suggested delay.
    }
  } finally {
    reader.releaseLock();
  }
}
