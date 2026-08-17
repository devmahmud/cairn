import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatInput } from "./ChatInput";

describe("ChatInput", () => {
  it("sends the trimmed message on Enter and clears the box", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput disabled={false} streaming={false} onSend={onSend} onStop={vi.fn()} />);

    const textbox = screen.getByRole("textbox", { name: /message/i });
    await user.type(textbox, "  hello there  ");
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("hello there");
    expect(textbox).toHaveValue("");
  });

  it("inserts a newline instead of sending on Shift+Enter", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput disabled={false} streaming={false} onSend={onSend} onStop={vi.fn()} />);

    const textbox = screen.getByRole("textbox", { name: /message/i });
    await user.type(textbox, "line one{Shift>}{Enter}{/Shift}line two");

    expect(onSend).not.toHaveBeenCalled();
    expect(textbox).toHaveValue("line one\nline two");
  });

  it("shows a stop button instead of send while streaming", async () => {
    const user = userEvent.setup();
    const onStop = vi.fn();
    render(<ChatInput disabled streaming onSend={vi.fn()} onStop={onStop} />);

    const stopButton = screen.getByRole("button", { name: /stop generating/i });
    await user.click(stopButton);
    expect(onStop).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /send message/i })).not.toBeInTheDocument();
  });

  it("does not send an empty or whitespace-only message", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput disabled={false} streaming={false} onSend={onSend} onStop={vi.fn()} />);

    await user.type(screen.getByRole("textbox", { name: /message/i }), "   ");
    await user.keyboard("{Enter}");

    expect(onSend).not.toHaveBeenCalled();
  });
});
