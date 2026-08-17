// Cairn frontend — chat feature store (BLUEPRINT.md §4.1, §4.3, §8 step 8).
//
// Zustand, feature-local (§4.3: server-state like conversation/message
// *history* belongs in TanStack Query, `features/chat/hooks/use-conversations.ts`
// -- this store only ever holds the *live* turn currently streaming in).
// `use-streaming-chat.ts` owns Layer 3 (the `switch` on `ChatSSEEvent.type`);
// this module is what that switch calls into, one action per event type, plus
// the `TypewriterEngine` wiring (§4.2) that turns `onMessageDelta`/`onToolResult`
// into a metered `visibleText`/`releasedToolResults` reveal.
//
// The moment a turn finishes (`message_end`, a genuine stream failure, or a
// user-requested stop), its content is folded into `completedTurns` and
// `activeTurn` goes back to `null` -- so `activeTurn` is *only* ever the
// in-flight turn, never a "just finished" one lingering around for
// `MessageList` to special-case.
//
// **A `ChatSSEEvent` of type `error` is *not* always terminal** -- verified
// against a real degraded-LLM run (no reachable model): `rag`/`tool`/
// `guardrail` node failures emit an `error` event *and then still finish the
// turn normally* (`message_delta` with the same graceful-fallback text,
// `message_end`) -- `modules/chat/chat_stream.py`'s `_EventTranslator`
// deliberately sends both; the `error` is a side-channel diagnostic, not a
// "stop reading" signal. Only two cases genuinely end the stream with no
// `message_end` to follow: the per-turn wall-clock budget (`mode=="timeout"`)
// and an unhandled exception in `_run_turn`'s own top-level `except`. Since
// an `error` event alone can't tell these apart from the recoverable case,
// this store keeps two different actions: `onGraphError` just records the
// latest one on `activeTurn.error` (informational, doesn't finalize --
// `message_delta`/`message_end` keep flowing normally after it); `onTurnFailed`
// is what actually folds the turn and disposes the engine, called by
// `use-streaming-chat.ts` only once it's established (the stream ended
// without ever reaching `message_end`) that nothing more is coming.
//
// Folding also sidesteps a real race: the assistant's reply is persisted
// server-side *after* every SSE event for it has already gone out
// (`modules/chat/chat_stream.py`'s `_persist_reply`), so refetching the
// TanStack Query history right after `message_end` could still race the
// write. `completedTurns` (client-only, cleared on conversation switch) is
// the turn's source of truth until the next real history fetch (a fresh
// mount) naturally picks it up from Postgres instead.

import { create } from "zustand";

import { TypewriterEngine } from "@/features/chat/lib/typewriter-engine";
import type {
  ChatErrorEvent,
  Citation,
  DecisionEvent,
  GuardrailEvent,
  ToolResultEvent,
} from "@/shared/types/sse-events";

export type TurnPhase = "connecting" | "streaming" | "reconnecting" | "done" | "error";

export interface ActiveTurn {
  conversationId: string;
  idempotencyKey: string;
  userMessageId: string;
  userText: string;
  assistantMessageId: string | null;
  streamId: string | null;
  lastEventId: string | null;
  agent: string | null;
  decision: DecisionEvent | null;
  guardrail: GuardrailEvent | null;
  visibleText: string;
  citations: Citation[];
  releasedToolResults: ToolResultEvent[];
  phase: TurnPhase;
  error: { code: string; message: string } | null;
  createdAt: string;
}

export interface CompletedTurnMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  toolResults: ToolResultEvent[];
  createdAt: string;
}

interface ChatState {
  activeTurn: ActiveTurn | null;
  completedTurns: CompletedTurnMessage[];
  reducedMotion: boolean;
  /** Set by `onTurnFailed`, alongside folding the turn into `completedTurns`
   * -- `activeTurn.error` would never be observable (both changes land in
   * the same `set()` call, §4.1's own note above), so the terminal failure
   * needs a home outside `activeTurn` for the UI to react to. Cleared by the
   * next `beginTurn`/`resetForConversation`. */
  lastError: { code: string; message: string } | null;
}

interface ChatActions {
  beginTurn(params: { conversationId: string; text: string }): ActiveTurn;
  setPhase(phase: TurnPhase): void;
  setStreamId(streamId: string | null): void;
  setLastEventId(eventId: string | null): void;
  onMessageStart(payload: { messageId: string; streamId: string | null }): void;
  onAgentSwitch(agent: string): void;
  onMessageDelta(text: string): void;
  onToolResult(toolResult: ToolResultEvent): void;
  onDecision(decision: DecisionEvent): void;
  onGuardrail(guardrail: GuardrailEvent): void;
  onMessageEnd(citations: Citation[]): void;
  onGraphError(error: ChatErrorEvent): void;
  onTurnFailed(error: { code: string; message: string }): void;
  onStopped(): void;
  resetForConversation(): void;
  setReducedMotion(value: boolean): void;
}

type ChatStore = ChatState & ChatActions;

let engine: TypewriterEngine | null = null;
// Full `ToolResultEvent` payloads keyed by the id `onToolResult` mints and
// hands to the engine as an opaque ordering token (§4.2's "ordered artifact
// deferral") -- `onArtifactReleased` looks the payload back up once the
// engine says it's this artifact's turn to appear.
const pendingArtifacts = new Map<string, ToolResultEvent>();

function disposeEngine(): void {
  engine?.dispose();
  engine = null;
}

function toCompletedPair(turn: ActiveTurn, assistantContent: string): CompletedTurnMessage[] {
  return [
    {
      id: turn.userMessageId,
      role: "user",
      content: turn.userText,
      citations: [],
      toolResults: [],
      createdAt: turn.createdAt,
    },
    {
      id: turn.assistantMessageId ?? `${turn.userMessageId}-assistant`,
      role: "assistant",
      content: assistantContent,
      citations: turn.citations,
      toolResults: turn.releasedToolResults,
      createdAt: new Date().toISOString(),
    },
  ];
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  activeTurn: null,
  completedTurns: [],
  lastError: null,
  reducedMotion:
    typeof window !== "undefined" ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false,

  beginTurn({ conversationId, text }) {
    disposeEngine();
    set({ lastError: null });
    engine = new TypewriterEngine(
      {
        onTextRevealed: (chunk) => {
          set((state) => {
            if (!state.activeTurn) return state;
            return { activeTurn: { ...state.activeTurn, visibleText: state.activeTurn.visibleText + chunk } };
          });
        },
        onArtifactReleased: (id) => {
          set((state) => {
            if (!state.activeTurn) return state;
            const pending = pendingArtifacts.get(id);
            pendingArtifacts.delete(id);
            if (!pending) return state;
            return {
              activeTurn: {
                ...state.activeTurn,
                releasedToolResults: [...state.activeTurn.releasedToolResults, pending],
              },
            };
          });
        },
      },
      { reducedMotion: get().reducedMotion },
    );
    pendingArtifacts.clear();

    const turn: ActiveTurn = {
      conversationId,
      idempotencyKey: crypto.randomUUID(),
      userMessageId: crypto.randomUUID(),
      userText: text,
      assistantMessageId: null,
      streamId: null,
      lastEventId: null,
      agent: null,
      decision: null,
      guardrail: null,
      visibleText: "",
      citations: [],
      releasedToolResults: [],
      phase: "connecting",
      error: null,
      createdAt: new Date().toISOString(),
    };
    set({ activeTurn: turn });
    return turn;
  },

  setPhase(phase) {
    set((state) => (state.activeTurn ? { activeTurn: { ...state.activeTurn, phase } } : state));
  },

  setStreamId(streamId) {
    set((state) => (state.activeTurn ? { activeTurn: { ...state.activeTurn, streamId } } : state));
  },

  setLastEventId(eventId) {
    set((state) =>
      state.activeTurn ? { activeTurn: { ...state.activeTurn, lastEventId: eventId } } : state,
    );
  },

  onMessageStart({ messageId, streamId }) {
    set((state) => {
      if (!state.activeTurn) return state;
      return {
        activeTurn: {
          ...state.activeTurn,
          assistantMessageId: messageId,
          streamId: streamId ?? state.activeTurn.streamId,
          phase: "streaming",
        },
      };
    });
  },

  onAgentSwitch(agent) {
    set((state) => (state.activeTurn ? { activeTurn: { ...state.activeTurn, agent } } : state));
  },

  onMessageDelta(text) {
    engine?.pushText(text);
  },

  onToolResult(toolResult) {
    const id = crypto.randomUUID();
    pendingArtifacts.set(id, toolResult);
    engine?.pushArtifact(id);
  },

  onDecision(decision) {
    set((state) => (state.activeTurn ? { activeTurn: { ...state.activeTurn, decision } } : state));
  },

  onGuardrail(guardrail) {
    set((state) => (state.activeTurn ? { activeTurn: { ...state.activeTurn, guardrail } } : state));
  },

  onMessageEnd(citations) {
    engine?.finalize();
    set((state) => {
      if (!state.activeTurn) return state;
      const finished: ActiveTurn = { ...state.activeTurn, citations, phase: "done" };
      return {
        activeTurn: null,
        completedTurns: [...state.completedTurns, ...toCompletedPair(finished, finished.visibleText)],
      };
    });
    disposeEngine();
  },

  onGraphError(error) {
    // Informational only -- see the module docstring: an `error` event is
    // frequently followed by a normal `message_delta`/`message_end` for the
    // same turn, so this must *not* touch the engine or finalize anything.
    set((state) =>
      state.activeTurn
        ? { activeTurn: { ...state.activeTurn, error: { code: error.code, message: error.message } } }
        : state,
    );
  },

  onTurnFailed(error) {
    engine?.finalize();
    set((state) => {
      if (!state.activeTurn) return state;
      const finished: ActiveTurn = { ...state.activeTurn, phase: "error", error };
      // The backend's own `ErrorEvent.message` is written to be shown as the
      // reply text (`modules/chat/chat_stream.py`'s `ErrorEvent(... message=
      // final_state.get("answer") or _GENERIC_ERROR_MESSAGE)`); a client-side
      // failure (parse error, a disconnect with no resume path) never typed
      // any text at all, so falling back to it there too keeps the
      // transcript from ending on a blank assistant bubble.
      const assistantContent = finished.visibleText || error.message;
      return {
        activeTurn: null,
        completedTurns: [...state.completedTurns, ...toCompletedPair(finished, assistantContent)],
        lastError: error,
      };
    });
    disposeEngine();
  },

  onStopped() {
    engine?.finalize();
    set((state) => {
      if (!state.activeTurn) return state;
      const finished: ActiveTurn = { ...state.activeTurn, phase: "done" };
      return {
        activeTurn: null,
        completedTurns: [...state.completedTurns, ...toCompletedPair(finished, finished.visibleText)],
      };
    });
    disposeEngine();
  },

  resetForConversation() {
    disposeEngine();
    pendingArtifacts.clear();
    set({ activeTurn: null, completedTurns: [], lastError: null });
  },

  setReducedMotion(value) {
    set({ reducedMotion: value });
    engine?.setReducedMotion(value);
  },
}));
