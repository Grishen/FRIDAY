import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Phase =
  | "idle"
  | "listening"
  | "thinking"
  | "checking_calendar"
  | "reading_documents"
  | "checking_email"
  | "executing"
  | "waiting_approval"
  | "synthesizing_response"
  | "done"
  | "error";

type Msg = { role: "user" | "assistant"; content: string; id?: string };

type State = {
  userId: string | null;
  sessionId: string | null;
  messages: Msg[];
  phase: Phase;
  streamingAssistant: string;
  speakAssistantReplies: boolean;
  pendingApproval: boolean;
  /** Latest high-risk gate from realtime status (approval UUID + tool label). */
  pendingApprovalId: string | null;
  pendingApprovalTool: string | null;
  toolLines: string[];
  setUserId: (id: string | null) => void;
  setSessionId: (id: string | null) => void;
  setPhase: (p: Phase) => void;
  clearChat: () => void;
  appendMessage: (m: Msg) => void;
  appendAssistantDelta: (t: string) => void;
  resetStreamingAssistant: () => void;
  setSpeakAssistantReplies: (v: boolean) => void;
  setToolLines: (lines: string[]) => void;
  setPendingApproval: (v: boolean) => void;
  setApprovalPrompt: (approvalId: string | null, tool: string | null) => void;
};

export const useFridayStore = create<State>()(
  persist(
    (set) => ({
      userId: null,
      sessionId: null,
      messages: [],
      phase: "idle",
      streamingAssistant: "",
      speakAssistantReplies: true,
      pendingApproval: false,
      pendingApprovalId: null,
      pendingApprovalTool: null,
      toolLines: [],
      setUserId: (id) => set({ userId: id }),
      setSessionId: (id) => set({ sessionId: id }),
      setPhase: (p) => set({ phase: p }),
      clearChat: () => set({ messages: [], streamingAssistant: "" }),
      appendMessage: (m) =>
        set((s) => ({
          messages: [...s.messages, m],
        })),
      appendAssistantDelta: (t) =>
        set((s) => ({
          streamingAssistant: s.streamingAssistant + t,
        })),
      resetStreamingAssistant: () => set({ streamingAssistant: "" }),
      setSpeakAssistantReplies: (v) => set({ speakAssistantReplies: v }),
      setToolLines: (lines) => set({ toolLines: lines }),
      setPendingApproval: (v) => set({ pendingApproval: v }),
      setApprovalPrompt: (approvalId, tool) =>
        set({
          pendingApprovalId: approvalId,
          pendingApprovalTool: tool,
          pendingApproval: approvalId !== null,
        }),
    }),
    {
      name: "friday-ui",
      partialize: (s) => ({
        userId: s.userId,
        sessionId: s.sessionId,
        speakAssistantReplies: s.speakAssistantReplies,
      }),
    },
  ),
);
