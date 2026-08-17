// Cairn frontend — the SSE pipeline's Layer 1 (fetch) + Layer 3 (typed
// dispatch) (BLUEPRINT.md §4.2, §8 step 8). Layer 2 is `shared/api/sse-parser.ts`.
//
// Resume policy (§4.2, §3.7): a clean end -- `message_end` received, or the
// body simply runs out right after it -- is *not* a disconnect; this hook
// returns without touching the network again. A stream that ends *without*
// `message_end`, or a `fetch`/read that throws, is treated as a disconnect:
// if the turn has a `streamId` (durable mode), reconnect to
// `GET /chat/stream/{id}?last_event_id=…` with capped backoff; simple mode
// has no `streamId` and therefore no resume path -- BLUEPRINT.md says to
// "handle that gracefully", so this surfaces one clear error event instead
// of retrying against an endpoint that would just 404. (An `error` SSE event
// on its own is *not* the disconnect signal -- see `chat-store.ts`'s module
// docstring for why that's frequently not the last event of a turn.)
//
// `stopStreaming()` aborts the client's own fetch *and* (durable mode only)
// calls `POST /chat/stream/{id}/stop` -- aborting alone only kills this
// browser tab's read of a durable stream; the decoupled server-side producer
// keeps running and writing frames until that endpoint says otherwise
// (`modules/chat/chat_stream.py`'s own docstring).
//
// `consumeStream`/`attemptResume` are plain hoisted `function`s, not
// `useCallback`s -- they call each other (a stream that dies mid-resume
// retries by re-entering `consumeStream`), and neither is ever handed to a
// child component or an effect's dependency array, so they don't need
// `useCallback`'s referential stability -- only the hook's returned
// `sendMessage`/`stopStreaming` do.

import { useCallback, useEffect, useRef } from "react";

import {
  ApiError,
  readStreamId,
  resumeChatStream,
  startChatTurn,
  stopChatStream,
} from "@/shared/api/client";
import { parseSSEStream, type ParsedSSEFrame } from "@/shared/api/sse-parser";
import { useChatStore } from "@/features/chat/stores/chat-store";
import { isChatSSEEventType, type ChatSSEEvent } from "@/shared/types/sse-events";

const RESUME_MAX_ATTEMPTS = 3;
const RESUME_BASE_DELAY_MS = 1000;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Unknown error.";
}

export interface UseStreamingChat {
  sendMessage(text: string): void;
  stopStreaming(): void;
}

export function useStreamingChat(conversationId: string | null): UseStreamingChat {
  const abortRef = useRef<AbortController | null>(null);
  const stoppedRef = useRef(false);

  useEffect(
    () => () => {
      stoppedRef.current = true;
      abortRef.current?.abort();
    },
    [conversationId],
  );

  function dispatch(frame: ParsedSSEFrame): void {
    const store = useChatStore.getState();
    if (frame.id) store.setLastEventId(frame.id);

    if (!isChatSSEEventType(frame.event)) {
      console.debug("cairn: ignoring unrecognized SSE event type", frame.event);
      return;
    }
    const event = frame.data as ChatSSEEvent;

    switch (event.type) {
      case "message_start":
        store.onMessageStart({ messageId: event.messageId, streamId: event.streamId ?? null });
        break;
      case "agent_switch":
        store.onAgentSwitch(event.agent);
        break;
      case "message_delta":
        store.onMessageDelta(event.text);
        break;
      case "tool_result":
        store.onToolResult(event);
        break;
      case "decision":
        store.onDecision(event);
        break;
      case "guardrail":
        store.onGuardrail(event);
        break;
      case "message_end":
        store.onMessageEnd(event.citations ?? []);
        break;
      case "error":
        // Not necessarily terminal -- see `chat-store.ts`'s module docstring.
        // A `message_delta`/`message_end` for this same turn frequently
        // still follows; `consumeStream` decides afterwards, once the
        // stream itself actually ends, whether this was the last word.
        store.onGraphError(event);
        break;
    }
  }

  function failTurn(code: string, message: string): void {
    useChatStore.getState().onTurnFailed({ code, message });
  }

  async function consumeStream(body: ReadableStream<Uint8Array>): Promise<void> {
    let sawMessageEnd = false;
    try {
      for await (const item of parseSSEStream(body)) {
        if (stoppedRef.current) return;
        if (item.kind === "parse-error") {
          failTurn("stream_parse_error", `Malformed event from server: ${item.error.message}`);
          return;
        }
        dispatch(item.frame);
        if (item.frame.event === "message_end") sawMessageEnd = true;
      }
    } catch {
      if (stoppedRef.current) return;
      await attemptResume();
      return;
    }
    if (sawMessageEnd || stoppedRef.current) return;

    // The stream closed without ever reaching `message_end`. If the graph
    // itself already told us why (a `timeout`/unhandled-exception `error`
    // event, `chat-store.ts`'s docstring) there's nothing to reconnect
    // to -- that error *is* the last word for this turn. Only a stream that
    // died with no explanation at all is worth trying to resume.
    const knownError = useChatStore.getState().activeTurn?.error;
    if (knownError) {
      useChatStore.getState().onTurnFailed(knownError);
      return;
    }
    await attemptResume();
  }

  async function attemptResume(): Promise<void> {
    const turn = useChatStore.getState().activeTurn;
    if (!turn?.streamId) {
      failTurn(
        "connection_lost",
        "Connection lost. This deployment isn't running durable streaming, so the reply can't be resumed — please retry.",
      );
      return;
    }

    useChatStore.getState().setPhase("reconnecting");
    for (let attempt = 1; attempt <= RESUME_MAX_ATTEMPTS; attempt += 1) {
      await delay(RESUME_BASE_DELAY_MS * 2 ** (attempt - 1));
      if (stoppedRef.current) return;

      const controller = new AbortController();
      abortRef.current = controller;
      const lastEventId = useChatStore.getState().activeTurn?.lastEventId ?? null;
      let response: Response;
      try {
        response = await resumeChatStream({
          streamId: turn.streamId,
          lastEventId,
          signal: controller.signal,
        });
      } catch {
        continue;
      }
      if (stoppedRef.current) return;
      if (!response.ok || !response.body) continue;

      useChatStore.getState().setPhase("streaming");
      await consumeStream(response.body);
      return;
    }
    failTurn("reconnect_failed", "Lost connection and couldn't reconnect. Please try sending again.");
  }

  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!conversationId || !trimmed) return;
      if (useChatStore.getState().activeTurn) return; // one in-flight turn at a time

      stoppedRef.current = false;
      const turn = useChatStore.getState().beginTurn({ conversationId, text: trimmed });

      void (async () => {
        const controller = new AbortController();
        abortRef.current = controller;
        let response: Response;
        try {
          response = await startChatTurn({
            conversationId,
            text: turn.userText,
            idempotencyKey: turn.idempotencyKey,
            signal: controller.signal,
          });
        } catch (err) {
          if (stoppedRef.current) return;
          failTurn("connection_failed", messageOf(err));
          return;
        }

        if (!response.ok) {
          if (stoppedRef.current) return;
          failTurn("request_failed", `The server rejected this message (${response.status}).`);
          return;
        }

        const streamId = readStreamId(response);
        if (streamId) useChatStore.getState().setStreamId(streamId);
        if (!response.body) {
          failTurn("empty_stream", "The server returned an empty response.");
          return;
        }
        await consumeStream(response.body);
      })();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `consumeStream`/`attemptResume`/`dispatch`/`failTurn` are hoisted function declarations recreated every render, not stateful values; including them would just churn `sendMessage`'s identity every render for no behavioral difference.
    [conversationId],
  );

  const stopStreaming = useCallback(() => {
    const turn = useChatStore.getState().activeTurn;
    if (!turn) return;
    stoppedRef.current = true;
    abortRef.current?.abort();
    useChatStore.getState().onStopped();
    if (turn.streamId) {
      void stopChatStream(turn.streamId).catch(() => {
        // Best-effort: the client has already stopped reading either way.
      });
    }
  }, []);

  return { sendMessage, stopStreaming };
}
