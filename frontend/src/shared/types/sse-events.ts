// Re-exports from the generated ./api.ts -- don't hand-duplicate these shapes.
import type { components } from "./api";

export type ChatSSEEvent = components["schemas"]["ChatSSEEvent"];
export type MessageStartEvent = components["schemas"]["MessageStartEvent"];
export type MessageDeltaEvent = components["schemas"]["MessageDeltaEvent"];
export type MessageEndEvent = components["schemas"]["MessageEndEvent"];
export type AgentSwitchEvent = components["schemas"]["AgentSwitchEvent"];
export type ToolResultEvent = components["schemas"]["ToolResultEvent"];
export type DecisionEvent = components["schemas"]["DecisionEvent"];
export type GuardrailEvent = components["schemas"]["GuardrailEvent"];
export type ChatErrorEvent = components["schemas"]["ErrorEvent"];
export type Citation = components["schemas"]["Citation"];

export type ChatSSEEventType = ChatSSEEvent["type"];

export function isChatSSEEventType(value: string): value is ChatSSEEventType {
  return (
    value === "message_start" ||
    value === "message_delta" ||
    value === "message_end" ||
    value === "agent_switch" ||
    value === "tool_result" ||
    value === "decision" ||
    value === "guardrail" ||
    value === "error"
  );
}
