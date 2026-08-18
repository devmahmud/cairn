// A "error" event isn't always terminal -- onGraphError just records it; onTurnFailed is the real finalizer.

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
  // Lives outside activeTurn because onTurnFailed clears activeTurn in the same set() call.
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
// Keyed by the id onToolResult mints as an opaque ordering token for the engine; onArtifactReleased looks it back up.
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
    // Informational only -- must not touch the engine or finalize the turn.
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
      // Falls back to the error message so a client-side failure (parse error, no resume path) doesn't end on a blank bubble.
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
