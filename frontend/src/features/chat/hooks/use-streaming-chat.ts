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
        // Not necessarily terminal -- a message_delta/message_end for this turn may still follow.
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

    // A graph-reported error is the terminal event for this turn; only an unexplained close is worth resuming.
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- consumeStream/attemptResume/dispatch/failTurn are hoisted functions, not stateful values.
    [conversationId],
  );

  const stopStreaming = useCallback(() => {
    const turn = useChatStore.getState().activeTurn;
    if (!turn) return;
    stoppedRef.current = true;
    abortRef.current?.abort();
    useChatStore.getState().onStopped();
    if (turn.streamId) {
      // Abort only stops this tab's read -- the durable server-side producer keeps running until told to stop.
      void stopChatStream(turn.streamId).catch(() => {});
    }
  }, []);

  return { sendMessage, stopStreaming };
}
