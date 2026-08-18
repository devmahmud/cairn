import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useDeleteConversation, useInvalidateMessages, useRenameConversation } from "./use-conversations";

const updateConversation = vi.fn();
const deleteConversation = vi.fn();

vi.mock("@/shared/api/client", () => ({
  createConversation: vi.fn(),
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  updateConversation: (...args: unknown[]) => updateConversation(...args),
  deleteConversation: (...args: unknown[]) => deleteConversation(...args),
}));

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useInvalidateMessages", () => {
  it("returns a referentially stable function across re-renders", () => {
    const queryClient = new QueryClient();
    const { result, rerender } = renderHook(() => useInvalidateMessages(), {
      wrapper: wrapper(queryClient),
    });

    const first = result.current;
    rerender();

    // ChatContainer puts this in a useEffect dependency array; an unstable identity would re-run it every render.
    expect(result.current).toBe(first);
  });

  it("marks the given conversation's message-history query stale", async () => {
    const queryClient = new QueryClient();
    const key = ["conversations", "conv-1", "messages"];
    queryClient.setQueryData(key, { items: [], next_cursor: null });
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);

    const { result } = renderHook(() => useInvalidateMessages(), {
      wrapper: wrapper(queryClient),
    });
    await result.current("conv-1");

    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it("does not invalidate a different conversation's cached history", async () => {
    const queryClient = new QueryClient();
    const otherKey = ["conversations", "conv-2", "messages"];
    queryClient.setQueryData(otherKey, { items: [], next_cursor: null });

    const { result } = renderHook(() => useInvalidateMessages(), {
      wrapper: wrapper(queryClient),
    });
    await result.current("conv-1");

    expect(queryClient.getQueryState(otherKey)?.isInvalidated).toBe(false);
  });
});

describe("useRenameConversation", () => {
  it("PATCHes the given title and invalidates the conversation list on success", async () => {
    const queryClient = new QueryClient();
    updateConversation.mockResolvedValueOnce({ id: "conv-1", title: "New title" });
    queryClient.setQueryData(["conversations"], { items: [], next_cursor: null });

    const { result } = renderHook(() => useRenameConversation(), { wrapper: wrapper(queryClient) });
    result.current.mutate({ conversationId: "conv-1", title: "New title" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(updateConversation).toHaveBeenCalledWith("conv-1", { title: "New title" });
    expect(queryClient.getQueryState(["conversations"])?.isInvalidated).toBe(true);
  });

  it("surfaces a failed rename without invalidating the list", async () => {
    const queryClient = new QueryClient();
    updateConversation.mockRejectedValueOnce(new Error("boom"));
    queryClient.setQueryData(["conversations"], { items: [], next_cursor: null });

    const { result } = renderHook(() => useRenameConversation(), { wrapper: wrapper(queryClient) });
    result.current.mutate({ conversationId: "conv-1", title: "New title" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(queryClient.getQueryState(["conversations"])?.isInvalidated).toBe(false);
  });
});

describe("useDeleteConversation", () => {
  it("DELETEs the given conversation and invalidates the conversation list on success", async () => {
    const queryClient = new QueryClient();
    deleteConversation.mockResolvedValueOnce(undefined);
    queryClient.setQueryData(["conversations"], { items: [], next_cursor: null });

    const { result } = renderHook(() => useDeleteConversation(), { wrapper: wrapper(queryClient) });
    result.current.mutate("conv-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(deleteConversation).toHaveBeenCalledWith("conv-1");
    expect(queryClient.getQueryState(["conversations"])?.isInvalidated).toBe(true);
  });

  it("surfaces a failed delete without invalidating the list", async () => {
    const queryClient = new QueryClient();
    deleteConversation.mockRejectedValueOnce(new Error("boom"));
    queryClient.setQueryData(["conversations"], { items: [], next_cursor: null });

    const { result } = renderHook(() => useDeleteConversation(), { wrapper: wrapper(queryClient) });
    result.current.mutate("conv-1");
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(queryClient.getQueryState(["conversations"])?.isInvalidated).toBe(false);
  });
});
