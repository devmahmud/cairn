// Deliberately generic -- ToolResultEvent has no schema for result's shape, so this renders whatever comes back.
import { Fragment } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import type { ToolResultEvent } from "@/shared/types/sse-events";

function tryParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

function KeyValueRows({ data }: { data: Record<string, unknown> }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
      {Object.entries(data).map(([key, value]) => (
        <Fragment key={key}>
          <dt className="font-medium text-muted-foreground">{key}</dt>
          <dd className="break-words">{typeof value === "string" ? value : JSON.stringify(value)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export function ToolArtifactCard({ toolResult }: { toolResult: ToolResultEvent }) {
  const parsed = tryParseJson(toolResult.result);

  return (
    <Card className="max-w-md bg-secondary/40">
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs text-muted-foreground">{toolResult.toolName}</CardTitle>
      </CardHeader>
      <CardContent>
        {parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (
          <KeyValueRows data={parsed as Record<string, unknown>} />
        ) : Array.isArray(parsed) ? (
          <ol className="list-inside list-decimal space-y-1 text-xs">
            {parsed.map((entry, i) => (
              <li key={i} className="break-words">
                {typeof entry === "string" ? entry : JSON.stringify(entry)}
              </li>
            ))}
          </ol>
        ) : (
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs">{toolResult.result}</pre>
        )}
      </CardContent>
    </Card>
  );
}
