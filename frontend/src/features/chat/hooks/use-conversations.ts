import { useCallback } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createConversation, listConversations, listMessages } from "@/shared/api/client";
import type { components } from "@/shared/types/api";

type MessageRead = components["schemas"]["MessageRead"];

const conversationsKey = ["conversations"] as const;
const messagesKey = (conversationId: string) => ["conversations", conversationId, "messages"] as const;

export function useConversations() {
  return useQuery({
    queryKey: conversationsKey,
    queryFn: () => listConversations({ limit: 50 }),
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (title?: string) => createConversation({ title: title ?? null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: conversationsKey });
    },
  });
}

// The API pages newest-first; reversed here so MessageList can render top-to-bottom chronological.
export function useMessages(conversationId: string | null) {
  return useQuery({
    queryKey: conversationId ? messagesKey(conversationId) : (["conversations", "none"] as const),
    queryFn: () => listMessages(conversationId as string, { limit: 200 }),
    enabled: conversationId !== null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    select: (page): MessageRead[] => [...page.items].reverse(),
  });
}

export function useInvalidateMessages(): (conversationId: string) => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(
    (conversationId: string) =>
      queryClient.invalidateQueries({ queryKey: messagesKey(conversationId) }),
    [queryClient],
  );
}
