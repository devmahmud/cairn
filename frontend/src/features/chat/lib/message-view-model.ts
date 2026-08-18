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

// Persisted history citations are raw snake_case graph-state dicts; live message_end citations are camelCase.
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
