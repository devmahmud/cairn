import { Plus } from "lucide-react";
import { Link, useNavigate } from "react-router";

import { useConversations, useCreateConversation } from "@/features/chat/hooks/use-conversations";
import { useAuthStore } from "@/features/auth/stores/auth-store";
import { Button } from "@/shared/components/ui/button";
import { ScrollArea } from "@/shared/components/ui/scroll-area";
import { Separator } from "@/shared/components/ui/separator";
import { cn } from "@/shared/lib/utils";

export function ConversationSidebar({ activeConversationId }: { activeConversationId: string | null }) {
  const navigate = useNavigate();
  const { data, isLoading } = useConversations();
  const createConversation = useCreateConversation();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  async function handleCreate(): Promise<void> {
    const conversation = await createConversation.mutateAsync(undefined);
    navigate(`/chat/${conversation.id}`);
  }

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-muted/20">
      <div className="p-3">
        <Button
          type="button"
          variant="secondary"
          className="w-full justify-start gap-2"
          onClick={() => void handleCreate()}
          disabled={createConversation.isPending}
        >
          <Plus className="size-4" />
          New conversation
        </Button>
      </div>
      <Separator />
      <ScrollArea className="flex-1" viewportClassName="p-2">
        <nav className="flex flex-col gap-1" aria-label="Conversations">
          {isLoading ? <p className="px-2 py-1 text-xs text-muted-foreground">Loading…</p> : null}
          {data?.items.map((conversation) => (
            <Link
              key={conversation.id}
              to={`/chat/${conversation.id}`}
              className={cn(
                "truncate rounded-md px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground",
                conversation.id === activeConversationId && "bg-accent text-accent-foreground",
              )}
            >
              {conversation.title ?? "Untitled conversation"}
            </Link>
          ))}
          {data && data.items.length === 0 ? (
            <p className="px-2 py-1 text-xs text-muted-foreground">No conversations yet.</p>
          ) : null}
        </nav>
      </ScrollArea>
      <Separator />
      <div className="flex items-center justify-between p-3 text-xs text-muted-foreground">
        <span className="truncate">{user?.email}</span>
        <Button type="button" variant="ghost" size="sm" onClick={() => void logout()}>
          Sign out
        </Button>
      </div>
    </aside>
  );
}
