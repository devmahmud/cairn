import * as React from "react";
import { Send, Square } from "lucide-react";

import { Button } from "@/shared/components/ui/button";
import { Textarea } from "@/shared/components/ui/textarea";

export interface ChatInputProps {
  disabled: boolean;
  streaming: boolean;
  onSend(text: string): void;
  onStop(): void;
}

export function ChatInput({ disabled, streaming, onSend, onStop }: ChatInputProps) {
  const [value, setValue] = React.useState("");

  function submit(): void {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="flex items-end gap-2 border-t bg-background p-3">
      <Textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Send a message…"
        disabled={disabled}
        aria-label="Message"
        className="max-h-40 rounded-xl"
      />
      {streaming ? (
        <Button
          type="button"
          variant="secondary"
          size="icon"
          className="rounded-full"
          onClick={onStop}
          aria-label="Stop generating"
        >
          <Square className="size-4" />
        </Button>
      ) : (
        <Button
          type="button"
          size="icon"
          className="rounded-full"
          onClick={submit}
          disabled={disabled || value.trim().length === 0}
          aria-label="Send message"
        >
          <Send className="size-4" />
        </Button>
      )}
    </div>
  );
}
