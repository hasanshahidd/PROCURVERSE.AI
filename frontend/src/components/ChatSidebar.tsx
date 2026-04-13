import { useState } from "react";
import { MessageSquare, Plus, Trash2, ChevronLeft, ChevronRight, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

interface ChatSession {
  id: string;
  title: string;
  timestamp: number;
  messageCount: number;
}

interface ChatSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
}

const SIDEBAR_TITLE_PREVIEW_LIMIT = 26;

const getSidebarPreviewTitle = (title: string): string => {
  const normalized = title.replace(/\s+/g, " ").trim();
  if (normalized.length <= SIDEBAR_TITLE_PREVIEW_LIMIT) {
    return normalized;
  }
  return `${normalized.slice(0, SIDEBAR_TITLE_PREVIEW_LIMIT).trim()}...`;
};

export function ChatSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
}: ChatSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <div className="w-12 border-r border-slate-200 flex flex-col items-center py-4 gap-3 bg-slate-50">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setCollapsed(false)}
          title="Expand sidebar"
          className="text-slate-500 hover:text-blue-600 hover:bg-blue-50"
        >
          <ChevronRight className="h-5 w-5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onNewChat}
          title="New chat"
          className="text-slate-500 hover:text-blue-600 hover:bg-blue-50"
        >
          <Plus className="h-5 w-5" />
        </Button>
      </div>
    );
  }

  return (
    <div className="relative border-r border-slate-200 flex flex-col w-[270px] flex-shrink-0 bg-slate-50">
      <div className="p-2.5 border-b border-slate-200 flex items-center justify-between gap-2">
        <h2 className="font-semibold text-sm flex items-center gap-2 text-slate-700">
          <MessageSquare className="h-4 w-4 text-blue-500" />
          Chat History
        </h2>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-slate-500 hover:text-blue-600 hover:bg-blue-50"
            onClick={onNewChat}
            title="New chat"
          >
            <Plus className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-slate-500 hover:text-blue-600 hover:bg-blue-50"
            onClick={() => setCollapsed(true)}
            title="Collapse sidebar"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-1.5 space-y-0.5">
          {sessions.length === 0 ? (
            <div className="text-center py-8 text-slate-400 text-sm">
              <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-40" />
              <p>No chat history yet</p>
              <p className="text-xs mt-1 text-slate-400">Start a new conversation</p>
            </div>
          ) : (
            sessions.map((session) => {
              const isActive = activeSessionId === session.id;
              const previewTitle = getSidebarPreviewTitle(session.title);
              return (
              <div key={session.id}>
                <div
                  className={cn(
                    "group relative rounded-lg transition-all flex items-center gap-1 px-2.5 py-2",
                    isActive
                      ? "bg-blue-50 border border-blue-200 shadow-sm"
                      : "border border-transparent hover:bg-white hover:shadow-sm"
                  )}
                >
                  <div
                    className="flex-1 min-w-0 cursor-pointer"
                    onClick={() => onSelectSession(session.id)}
                  >
                    <p
                      className={cn(
                        "block w-full text-sm font-medium truncate",
                        isActive ? "text-blue-700" : "text-slate-600"
                      )}
                      title={session.title}
                    >
                      {previewTitle}
                    </p>
                  </div>

                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className={cn(
                          "h-6 w-6 flex-shrink-0",
                          isActive
                            ? "opacity-100 text-blue-500 hover:bg-blue-100"
                            : "opacity-0 group-hover:opacity-70 text-slate-400 hover:text-slate-600 hover:bg-slate-100"
                        )}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-32 bg-white border-slate-200 shadow-lg">
                      <DropdownMenuItem
                        className="text-red-500 focus:text-red-600 focus:bg-red-50 cursor-pointer"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(session.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4 mr-2" />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
              );
            })
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
