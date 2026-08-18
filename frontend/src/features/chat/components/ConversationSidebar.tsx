import { useEffect, useRef, useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { Link, useNavigate } from "react-router";

import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useRenameConversation,
} from "@/features/chat/hooks/use-conversations";
import { useAuthStore } from "@/features/auth/stores/auth-store";
import { Button } from "@/shared/components/ui/button";
import { ScrollArea } from "@/shared/components/ui/scroll-area";
import { Separator } from "@/shared/components/ui/separator";
import { Wordmark } from "@/shared/components/Wordmark";
import { cn } from "@/shared/lib/utils";
import type { components } from "@/shared/types/api";

type ConversationRead = components["schemas"]["ConversationRead"];

function ConversationRow({
  conversation,
  isActive,
  onDeletedActive,
}: {
  conversation: ConversationRead;
  isActive: boolean;
  onDeletedActive: () => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState(conversation.title ?? "");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const skipBlurSaveRef = useRef(false);
  const renameConversation = useRenameConversation();
  const deleteConversation = useDeleteConversation();

  useEffect(() => {
    if (isEditing) inputRef.current?.select();
  }, [isEditing]);

  function startEditing(event: React.MouseEvent): void {
    event.preventDefault();
    setTitleDraft(conversation.title ?? "");
    setIsEditing(true);
  }

  function commitEdit(): void {
    setIsEditing(false);
    const trimmed = titleDraft.trim();
    if (!trimmed || trimmed === (conversation.title ?? "")) return;
    renameConversation.mutate({ conversationId: conversation.id, title: trimmed });
  }

  function cancelEdit(): void {
    skipBlurSaveRef.current = true;
    setIsEditing(false);
  }

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === "Enter") {
      event.preventDefault();
      commitEdit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelEdit();
    }
  }

  function handleInputBlur(): void {
    if (skipBlurSaveRef.current) {
      skipBlurSaveRef.current = false;
      return;
    }
    commitEdit();
  }

  function requestDelete(event: React.MouseEvent): void {
    event.preventDefault();
    setConfirmingDelete(true);
  }

  function cancelDelete(event: React.MouseEvent): void {
    event.preventDefault();
    setConfirmingDelete(false);
  }

  function confirmDelete(event: React.MouseEvent): void {
    event.preventDefault();
    deleteConversation.mutate(conversation.id, {
      onSuccess: () => {
        if (isActive) onDeletedActive();
      },
    });
  }

  if (isEditing) {
    return (
      <div className="px-1 py-0.5">
        <input
          ref={inputRef}
          autoFocus
          value={titleDraft}
          onChange={(event) => setTitleDraft(event.target.value)}
          onKeyDown={handleInputKeyDown}
          onBlur={handleInputBlur}
          aria-label="Conversation title"
          className="h-7 w-full rounded-md border border-input bg-background px-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/80"
        />
      </div>
    );
  }

  if (confirmingDelete) {
    return (
      <div className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs">
        <span className="flex-1 truncate text-muted-foreground">Delete this conversation?</span>
        <button
          type="button"
          onClick={confirmDelete}
          disabled={deleteConversation.isPending}
          className="shrink-0 rounded px-1.5 py-0.5 font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
        >
          Delete
        </button>
        <button
          type="button"
          onClick={cancelDelete}
          className="shrink-0 rounded px-1.5 py-0.5 text-muted-foreground hover:bg-accent"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="group/row relative">
      {isActive ? (
        <span className="absolute top-1.5 bottom-1.5 left-0 w-0.5 rounded-full bg-lichen" aria-hidden="true" />
      ) : null}
      <Link
        to={`/chat/${conversation.id}`}
        className={cn(
          "block truncate rounded-md px-2.5 py-1.5 pr-14 text-sm text-foreground/85 hover:bg-accent hover:text-accent-foreground",
          isActive && "bg-accent font-medium text-accent-foreground",
        )}
      >
        {conversation.title ?? "Untitled conversation"}
      </Link>
      <div className="absolute inset-y-0 right-1 flex items-center gap-0.5 opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 [@media(hover:none)]:opacity-100">
        <button
          type="button"
          onClick={startEditing}
          aria-label="Rename conversation"
          className="rounded p-1 text-muted-foreground hover:bg-background hover:text-foreground"
        >
          <Pencil className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={requestDelete}
          aria-label="Delete conversation"
          className="rounded p-1 text-muted-foreground hover:bg-background hover:text-destructive"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

export function ConversationSidebar({
  activeConversationId,
  open = true,
  onClose,
}: {
  activeConversationId: string | null;
  open?: boolean;
  onClose?: () => void;
}) {
  const navigate = useNavigate();
  const { data, isLoading } = useConversations();
  const createConversation = useCreateConversation();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  async function handleCreate(): Promise<void> {
    const conversation = await createConversation.mutateAsync(undefined);
    navigate(`/chat/${conversation.id}`);
    onClose?.();
  }

  return (
    <>
      {open ? (
        <div
          className="fixed inset-0 z-40 bg-foreground/30 sm:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      ) : null}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-72 shrink-0 flex-col border-r bg-muted transition-transform duration-200 ease-out",
          "sm:static sm:z-auto sm:w-64 sm:translate-x-0 sm:transition-none",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between p-3 pb-2">
          <Wordmark />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close conversations"
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground sm:hidden"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="px-3 pb-3">
          <Button
            type="button"
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
              <ConversationRow
                key={conversation.id}
                conversation={conversation}
                isActive={conversation.id === activeConversationId}
                onDeletedActive={() => navigate("/chat")}
              />
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
    </>
  );
}
