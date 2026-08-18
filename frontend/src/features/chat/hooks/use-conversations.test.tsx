import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useInvalidateMessages } from "./use-conversations";

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
