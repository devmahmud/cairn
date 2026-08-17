// Cairn frontend — history/live-turn view-model normalization (BLUEPRINT.md
// §8 step 8).
//
// `MessageRead.citations` (`shared/types/api.ts`) is untyped JSONB -- it's
// the *raw* graph-state citation dicts `_persist_reply`
// (`modules/chat/chat_stream.py`) writes straight to Postgres, which are
// `agents/chat/nodes/rag.py`'s own snake_case shape (`chunk_id`/`document_id`),
// never passed through `modules/chat/sse.py::Citation`'s `to_camel` wire
// alias the way a *live* `message_end` event's citations are. Reading a
// persisted conversation's history and a turn that's mid-stream must
// therefore agree on one shape -- `normalizeCitation` below is that one
// place, accepting either casing so `MessageBubble` never has to care which
// source a citation came from.

import type { CompletedTurnMessage } from "@/features/chat/stores/chat-store";
import type { components } from "@/shared/types/api";
import type { Citation, ToolResultEvent } from "@/shared/types/sse-events";

type MessageRead = components["schemas"]["MessageRead"];

export interface ChatMessageVM {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  citations: Citation[];
  toolResults: ToolResultEvent[];
}

function normalizeCitation(raw: Record<string, unknown>): Citation {
  return {
    index: Number(raw.index ?? 0),
    chunkId: String(raw.chunkId ?? raw.chunk_id ?? ""),
    documentId: String(raw.documentId ?? raw.document_id ?? ""),
    source: typeof raw.source === "string" ? raw.source : null,
    score: Number(raw.score ?? 0),
  };
}

const KNOWN_ROLES: readonly ChatMessageVM["role"][] = ["user", "assistant", "system", "tool"];

export function fromMessageRead(message: MessageRead): ChatMessageVM {
  const role = KNOWN_ROLES.find((r) => r === message.role) ?? "assistant";
  return {
    id: message.id,
    role,
    content: message.content,
    citations: message.citations.map((c) => normalizeCitation(c)),
    toolResults: [],
  };
}

export function fromCompletedTurn(message: CompletedTurnMessage): ChatMessageVM {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    citations: message.citations,
    toolResults: message.toolResults,
  };
}
