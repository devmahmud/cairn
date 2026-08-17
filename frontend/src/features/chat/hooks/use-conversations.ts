// Cairn frontend — server-state hooks (BLUEPRINT.md §4.3, §8 step 8).
//
// "Server-state (conversation list/history) is better as TanStack Query than
// a Zustand store" -- `stores/chat-store.ts` only ever holds the live turn.

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

/** `list_for_conversation` (`backend/src/modules/conversations/repository.py`)
 * pages newest-first (keyset pagination, §3.3) -- reversed here so
 * `MessageList` can render top-to-bottom chronological without knowing
 * that's a REST convention, not a chat-transcript one. */
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
  return (conversationId: string) =>
    queryClient.invalidateQueries({ queryKey: messagesKey(conversationId) });
}
