// Cairn frontend — SSE event types (BLUEPRINT.md §4.1, §4.3, §8 step 8).
//
// A thin, hand-written wrapper over `./api.ts` (the one file
// `pnpm run contract` regenerates, §4.3) -- not a second generated file and
// not a hand-maintained duplicate of the backend's shapes. `ChatSSEEvent`
// here is a re-export of `components["schemas"]["ChatSSEEvent"]`, the exact
// discriminated union `modules/chat/sse.py::register_sse_schema` merges into
// `/openapi.json` -- redefining these fields by hand anywhere in the
// frontend would be the one thing contract-first streaming (§4.3) exists to
// prevent. Widen the union here, in one place, if a client fork ever adds an
// event type via an `examples/` pack + its own OpenAPI registration.

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
