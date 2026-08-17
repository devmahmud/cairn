import { describe, expect, it } from "vitest";

import { parseSSEStream } from "./sse-parser";

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const items: T[] = [];
  for await (const item of iterable) items.push(item);
  return items;
}

describe("parseSSEStream", () => {
  it("parses a well-formed event, using the event field as the type", async () => {
    const stream = streamFromChunks([
      'id: 1\nevent: message_delta\ndata: {"type":"message_delta","text":"hi"}\n\n',
    ]);
    const items = await collect(parseSSEStream(stream));
    expect(items).toEqual([
      {
        kind: "event",
        frame: { id: "1", event: "message_delta", data: { type: "message_delta", text: "hi" } },
      },
    ]);
  });

  it("skips comment/heartbeat lines without dispatching an event", async () => {
    const payload = JSON.stringify({ type: "decision", intent: "x", confidence: 0.9 });
    const stream = streamFromChunks([`: ping\n\nevent: decision\ndata: ${payload}\n\n`]);
    const items = await collect(parseSSEStream(stream));
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "event", frame: { event: "decision" } });
  });

  it("defaults the event type to \"message\" when no event: field is given", async () => {
    const stream = streamFromChunks(['data: {"foo":"bar"}\n\n']);
    const items = await collect(parseSSEStream(stream));
    expect(items).toEqual([{ kind: "event", frame: { id: null, event: "message", data: { foo: "bar" } } }]);
  });

  it("surfaces malformed JSON as a typed parse-error, not a thrown exception", async () => {
    const stream = streamFromChunks(["event: message_delta\ndata: {not valid json\n\n"]);
    const items = await collect(parseSSEStream(stream));
    expect(items).toHaveLength(1);
    expect(items[0]?.kind).toBe("parse-error");
    if (items[0]?.kind === "parse-error") {
      expect(items[0].error.raw).toBe("{not valid json");
    }
  });

  it("keeps parsing subsequent well-formed events after a parse error", async () => {
    const stream = streamFromChunks([
      "data: not json\n\n",
      'event: message_end\ndata: {"type":"message_end","messageId":"m1"}\n\n',
    ]);
    const items = await collect(parseSSEStream(stream));
    expect(items).toHaveLength(2);
    expect(items[0]?.kind).toBe("parse-error");
    expect(items[1]).toMatchObject({ kind: "event", frame: { event: "message_end" } });
  });

  it("reassembles frames split across multiple stream chunks", async () => {
    const stream = streamFromChunks(["event: message_d", 'elta\ndata: {"a":1}', "\n\n"]);
    const items = await collect(parseSSEStream(stream));
    expect(items).toEqual([{ kind: "event", frame: { id: null, event: "message_delta", data: { a: 1 } } }]);
  });

  it("carries the last seen id across events that don't repeat it", async () => {
    const stream = streamFromChunks([
      'id: 7\nevent: a\ndata: {"n":1}\n\n',
      'event: b\ndata: {"n":2}\n\n',
    ]);
    const items = await collect(parseSSEStream(stream));
    expect(items[0]).toMatchObject({ frame: { id: "7" } });
    expect(items[1]).toMatchObject({ frame: { id: "7" } });
  });
});
