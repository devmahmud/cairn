import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationSidebar } from "./ConversationSidebar";

const listConversations = vi.fn();
const createConversation = vi.fn();
const updateConversation = vi.fn();
const deleteConversation = vi.fn();
const navigate = vi.fn();

vi.mock("@/shared/api/client", () => ({
  listConversations: (...args: unknown[]) => listConversations(...args),
  createConversation: (...args: unknown[]) => createConversation(...args),
  updateConversation: (...args: unknown[]) => updateConversation(...args),
  deleteConversation: (...args: unknown[]) => deleteConversation(...args),
  listMessages: vi.fn(),
}));

vi.mock("@/features/auth/stores/auth-store", () => ({
  useAuthStore: (selector: (state: { user: { email: string }; logout: () => Promise<void> }) => unknown) =>
    selector({ user: { email: "user@example.com" }, logout: vi.fn() }),
}));

vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return { ...actual, useNavigate: () => navigate };
});

const CONVERSATION = {
  id: "conv-1",
  title: "Old title",
  status: "active",
  summary: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  user_id: "user-1",
};

beforeEach(() => {
  vi.resetAllMocks();
});

function renderSidebar(activeConversationId: string | null) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }
  return render(<ConversationSidebar activeConversationId={activeConversationId} />, { wrapper: Wrapper });
}

describe("ConversationSidebar rename", () => {
  it("renames inline on Enter and PATCHes the new title", async () => {
    const user = userEvent.setup();
    listConversations.mockResolvedValue({ items: [CONVERSATION], next_cursor: null });
    updateConversation.mockResolvedValue({ ...CONVERSATION, title: "New title" });

    renderSidebar(null);
    await screen.findByRole("link", { name: "Old title" });

    await user.click(screen.getByRole("button", { name: "Rename conversation" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    await user.clear(input);
    await user.type(input, "New title{Enter}");

    await waitFor(() => expect(updateConversation).toHaveBeenCalledWith("conv-1", { title: "New title" }));
    await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(2));
  });

  it("cancels on Escape without calling PATCH", async () => {
    const user = userEvent.setup();
    listConversations.mockResolvedValue({ items: [CONVERSATION], next_cursor: null });

    renderSidebar(null);
    await screen.findByRole("link", { name: "Old title" });

    await user.click(screen.getByRole("button", { name: "Rename conversation" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    await user.type(input, " edited{Escape}");

    expect(screen.queryByRole("textbox", { name: "Conversation title" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Old title" })).toBeInTheDocument();
    expect(updateConversation).not.toHaveBeenCalled();
  });
});

describe("ConversationSidebar delete", () => {
  it("requires confirmation, then DELETEs and navigates away when the deleted conversation is active", async () => {
    const user = userEvent.setup();
    listConversations.mockResolvedValue({ items: [CONVERSATION], next_cursor: null });
    deleteConversation.mockResolvedValue(undefined);

    renderSidebar("conv-1");
    await screen.findByRole("link", { name: "Old title" });

    await user.click(screen.getByRole("button", { name: "Delete conversation" }));
    expect(deleteConversation).not.toHaveBeenCalled();
    expect(screen.getByText("Delete this conversation?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith("conv-1"));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/chat"));
    await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(2));
  });

  it("does not navigate away when the deleted conversation is not the active one", async () => {
    const user = userEvent.setup();
    listConversations.mockResolvedValue({ items: [CONVERSATION], next_cursor: null });
    deleteConversation.mockResolvedValue(undefined);

    renderSidebar("some-other-conversation");
    await screen.findByRole("link", { name: "Old title" });

    await user.click(screen.getByRole("button", { name: "Delete conversation" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith("conv-1"));
    expect(navigate).not.toHaveBeenCalledWith("/chat");
  });

  it("cancels the confirmation without deleting", async () => {
    const user = userEvent.setup();
    listConversations.mockResolvedValue({ items: [CONVERSATION], next_cursor: null });

    renderSidebar(null);
    await screen.findByRole("link", { name: "Old title" });

    await user.click(screen.getByRole("button", { name: "Delete conversation" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("link", { name: "Old title" })).toBeInTheDocument();
    expect(deleteConversation).not.toHaveBeenCalled();
  });
});
