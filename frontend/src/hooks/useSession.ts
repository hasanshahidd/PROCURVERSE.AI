/**
 * useSession — universal session hook for Layer 3 session-driven UI.
 *
 * Subscribes to GET /api/sessions/:id/events via SSE (fetch + ReadableStream
 * so we can attach the Authorization header, which EventSource does not
 * support). Runs a pure reducer over the ordered event log to derive the
 * current session view state.
 *
 * Contract (from the architectural plan):
 *  - Events must arrive in sequence_number order; gaps trigger a re-sync.
 *  - Replaying the same event (by sequence_number) is a no-op (idempotent).
 *  - No hidden state — everything the UI renders is a projection of the log.
 *
 * Returns:
 *   { session, events, gate, lastSequence, loading, error, resume, cancel }
 */
import { useEffect, useReducer, useRef, useCallback } from "react";
import { BASE_URL } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type SessionEventType =
  | "session_started"
  | "phase_started"
  | "phase_completed"
  | "phase_failed"
  | "gate_opened"
  | "gate_resolved"
  | "agent_started"
  | "agent_finished"
  | "agent_failed"
  | "tool_called"
  | "session_completed"
  | "session_failed"
  | "session_cancelled";

export interface SessionEvent {
  event_id: string;
  session_id: string;
  sequence_number: number;
  event_type: SessionEventType | string;
  actor: string;
  payload: Record<string, any>;
  caused_by_event_id?: string | null;
  created_at: string;
}

export interface OpenGate {
  gate_id: string;
  gate_type: string;
  gate_ref: Record<string, any>;
  decision_context: Record<string, any>;
  required_role?: string | null;
  status: "pending" | "resolved" | "expired";
  created_at: string;
}

export interface SessionMaster {
  session_id: string;
  session_kind: string;
  initiated_by_user_id: string;
  current_phase: string;
  current_status: "running" | "paused_human" | "completed" | "failed" | "cancelled";
  workflow_run_id?: string | null;
  request_summary: Record<string, any>;
  last_event_sequence: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  open_gates?: OpenGate[];
}

interface SessionView {
  session: SessionMaster | null;
  events: SessionEvent[];
  gate: OpenGate | null;
  lastSequence: number;
  completedPhases: string[];
  currentPhase: string;
  status: SessionMaster["current_status"];
  loading: boolean;
  error: string | null;
  needsResync: boolean;
}

type Action =
  | { type: "loading" }
  | { type: "session_loaded"; session: SessionMaster }
  | { type: "session_event"; event: SessionEvent }
  | { type: "snapshot_replay"; atSequence: number; state: Record<string, any> }
  | { type: "replay_end"; lastSequence: number }
  | { type: "stream_end"; status: SessionMaster["current_status"]; lastSequence: number }
  | { type: "gate_updated"; gate: OpenGate | null }
  | { type: "error"; error: string }
  | { type: "reset_for_resync"; resyncFrom: number };

const INITIAL: SessionView = {
  session: null,
  events: [],
  gate: null,
  lastSequence: 0,
  completedPhases: [],
  currentPhase: "starting",
  status: "running",
  loading: true,
  error: null,
  needsResync: false,
};

// ─────────────────────────────────────────────────────────────────────────────
// Reducer — pure projection of events onto view state
// ─────────────────────────────────────────────────────────────────────────────

function reducer(state: SessionView, action: Action): SessionView {
  switch (action.type) {
    case "loading":
      return { ...state, loading: true, error: null };

    case "session_loaded": {
      const openGate = (action.session.open_gates || []).find((g) => g.status === "pending") || null;
      return {
        ...state,
        session: action.session,
        gate: openGate,
        currentPhase: action.session.current_phase,
        status: action.session.current_status,
        loading: false,
      };
    }

    case "session_event": {
      const event = action.event;
      const seq = Number(event.sequence_number || 0);

      // Idempotency: skip events we've already applied
      if (seq <= state.lastSequence) return state;

      // Gap detection: if we skipped sequence numbers, re-sync from a window
      // behind the last confirmed event (covers reorder/dup deliveries)
      if (state.lastSequence > 0 && seq !== state.lastSequence + 1) {
        return {
          ...state,
          needsResync: true,
          error: `sequence gap: expected ${state.lastSequence + 1}, got ${seq}`,
        };
      }

      const nextState: SessionView = {
        ...state,
        events: [...state.events, event],
        lastSequence: seq,
      };

      const phase = event.payload?.phase as string | undefined;

      switch (event.event_type) {
        case "session_started":
          return nextState;

        case "phase_started":
          return phase ? { ...nextState, currentPhase: phase, status: "running" } : nextState;

        case "phase_completed":
          return phase
            ? {
                ...nextState,
                completedPhases: nextState.completedPhases.includes(phase)
                  ? nextState.completedPhases
                  : [...nextState.completedPhases, phase],
              }
            : nextState;

        case "phase_failed":
          return {
            ...nextState,
            status: "failed",
            error: (event.payload?.error as string) || `phase ${phase || "?"} failed`,
          };

        case "gate_opened":
          return {
            ...nextState,
            status: "paused_human",
            gate: {
              gate_id: (event.payload?.gate_id as string) || "",
              gate_type: (event.payload?.gate_type as string) || "",
              gate_ref: (event.payload?.gate_ref as Record<string, any>) || {},
              decision_context: (event.payload?.decision_context as Record<string, any>) || {},
              required_role: (event.payload?.required_role as string) || null,
              status: "pending",
              created_at: event.created_at,
            },
          };

        case "gate_resolved":
          return { ...nextState, gate: null, status: "running" };

        case "session_completed":
          return { ...nextState, status: "completed", gate: null };

        case "session_failed":
          return {
            ...nextState,
            status: "failed",
            gate: null,
            error: (event.payload?.reason as string) || (event.payload?.error as string) || "session failed",
          };

        case "session_cancelled":
          return { ...nextState, status: "cancelled", gate: null };

        default:
          // agent_started / agent_finished / tool_called — log only, no state shift
          return nextState;
      }
    }

    case "snapshot_replay": {
      // HF-4 / R8 / R19 — fast-forward to the folded state captured at
      // action.atSequence. This REPLACES the projected state instead of
      // appending; subsequent `session_event` frames (sequence_number >
      // atSequence) build on top of it normally.
      //
      // Synthetic events: the snapshot includes `phase_payloads` — the
      // full payload from each phase_completed event. We synthesize
      // phase_completed events so components like POResultCard can find
      // the PO data they need without a separate fetch.
      const snap = action.state || {};
      const completedPhases: string[] = Array.isArray(snap.completed_phases)
        ? (snap.completed_phases as string[])
        : [];
      const currentPhase =
        typeof snap.current_phase === "string" && snap.current_phase
          ? (snap.current_phase as string)
          : state.currentPhase;
      const currentStatus = (snap.current_status as SessionMaster["current_status"]) || state.status;

      // Synthesize phase_completed events from snapshot payloads
      const phasePayloads: Record<string, Record<string, any>> =
        (snap.phase_payloads as Record<string, Record<string, any>>) || {};
      const syntheticEvents: SessionEvent[] = completedPhases
        .filter((phase) => phasePayloads[phase])
        .map((phase, idx) => ({
          event_id: `snapshot-${phase}`,
          session_id: snap.session_id || "",
          sequence_number: idx + 1,
          event_type: "phase_completed" as SessionEventType,
          actor: "orchestrator",
          payload: phasePayloads[phase],
          created_at: snap.last_event_at || new Date().toISOString(),
        }));

      // Restore open gate from snapshot (if session is paused at a gate)
      let restoredGate: OpenGate | null = null;
      const openGatesMap = snap.open_gates as Record<string, any> | undefined;
      if (openGatesMap && typeof openGatesMap === "object" && !Array.isArray(openGatesMap)) {
        const gateEntries = Object.values(openGatesMap);
        if (gateEntries.length > 0) {
          const g = gateEntries[0] as Record<string, any>;
          restoredGate = {
            gate_id: (g.gate_id as string) || "",
            gate_type: (g.gate_type as string) || "",
            gate_ref: (g.gate_ref as Record<string, any>) || {},
            decision_context: (g.decision_context as Record<string, any>) || {},
            required_role: (g.required_role as string) || null,
            status: "pending",
            created_at: snap.last_event_at || new Date().toISOString(),
          };
        }
      }

      return {
        ...state,
        events: syntheticEvents,
        lastSequence: Math.max(state.lastSequence, action.atSequence),
        completedPhases,
        currentPhase,
        status: currentStatus,
        gate: restoredGate,
      };
    }

    case "replay_end":
      return { ...state, lastSequence: Math.max(state.lastSequence, action.lastSequence), loading: false };

    case "stream_end":
      return { ...state, status: action.status, lastSequence: action.lastSequence, loading: false };

    case "gate_updated":
      return { ...state, gate: action.gate };

    case "error":
      return { ...state, error: action.error, loading: false };

    case "reset_for_resync":
      return {
        ...state,
        lastSequence: action.resyncFrom,
        needsResync: false,
      };

    default:
      return state;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Auth helper
// ─────────────────────────────────────────────────────────────────────────────

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("authToken") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export interface UseSessionReturn extends SessionView {
  resume: (
    gateId: string,
    action: string,
    payload?: Record<string, any>
  ) => Promise<{ success: boolean; error?: string }>;
  cancel: (reason?: string) => Promise<{ success: boolean; error?: string }>;
  refetchSession: () => Promise<void>;
}

export function useSession(sessionId: string | undefined): UseSessionReturn {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string | undefined>(sessionId);
  sessionIdRef.current = sessionId;

  // ── Fetch master session row (one-shot) ──────────────────────────────────
  const fetchSession = useCallback(async () => {
    if (!sessionId) return;
    const sidShort = sessionId.slice(0, 8);
    console.log(`[useSession] FETCH master session=${sidShort}`);
    try {
      const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}`, {
        headers: { ...authHeaders() },
        credentials: "include",
      });
      if (!res.ok) {
        console.error(`[useSession] FETCH FAILED session=${sidShort} status=${res.status}`);
        dispatch({ type: "error", error: `Failed to load session (${res.status})` });
        return;
      }
      const data = (await res.json()) as SessionMaster;
      console.log(
        `[useSession] FETCH OK session=${sidShort} phase=${data.current_phase} status=${data.current_status} last_seq=${data.last_event_sequence} open_gates=${(data.open_gates || []).length}`
      );
      dispatch({ type: "session_loaded", session: data });
    } catch (err) {
      console.error(`[useSession] FETCH EXC session=${sidShort}`, err);
      dispatch({ type: "error", error: String((err as Error).message || err) });
    }
  }, [sessionId]);

  // ── Stream session events via fetch + ReadableStream ─────────────────────
  const streamEvents = useCallback(
    async (sinceSeq: number) => {
      if (!sessionId) return;
      const sidShort = sessionId.slice(0, 8);
      const abortCtrl = new AbortController();
      abortRef.current = abortCtrl;
      const t0 = Date.now();
      let frameCount = 0;
      let eventCount = 0;
      console.log(`[useSession] STREAM OPEN session=${sidShort} since=${sinceSeq}`);

      try {
        const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/events?since=${sinceSeq}`, {
          headers: { ...authHeaders(), Accept: "text/event-stream" },
          credentials: "include",
          signal: abortCtrl.signal,
        });

        if (!res.ok || !res.body) {
          console.error(`[useSession] STREAM CONNECT FAILED session=${sidShort} status=${res.status}`);
          dispatch({ type: "error", error: `SSE connect failed (${res.status})` });
          return;
        }
        console.log(`[useSession] STREAM CONNECTED session=${sidShort} status=${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentEventName = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            console.log(`[useSession] STREAM DONE session=${sidShort} frames=${frameCount} events=${eventCount} dur=${Date.now() - t0}ms`);
            break;
          }
          if (sessionIdRef.current !== sessionId) {
            // Caller swapped sessions — drop this stream
            console.log(`[useSession] STREAM DROPPED session=${sidShort} (caller swapped to ${sessionIdRef.current?.slice(0, 8) || "none"})`);
            try { await reader.cancel(); } catch { /* noop */ }
            return;
          }

          buffer += decoder.decode(value, { stream: true });
          // SSE frames are separated by a blank line (\n\n)
          const frames = buffer.split("\n\n");
          buffer = frames.pop() || ""; // keep incomplete tail

          for (const frame of frames) {
            frameCount++;
            currentEventName = "";
            let dataLine = "";
            for (const line of frame.split("\n")) {
              if (line.startsWith(":")) continue; // keepalive comment
              if (line.startsWith("event:")) {
                currentEventName = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                dataLine += line.slice(5).trim();
              }
            }
            if (!dataLine) continue;
            let parsed: any;
            try { parsed = JSON.parse(dataLine); } catch (e) {
              console.warn(`[useSession] STREAM bad-json session=${sidShort} frame=${frameCount}`, e);
              continue;
            }

            if (currentEventName === "session_event") {
              eventCount++;
              const ev = parsed as SessionEvent;
              console.log(
                `[useSession] EVENT session=${sidShort} seq=${ev.sequence_number} type=${ev.event_type} actor=${ev.actor} payload_keys=${Object.keys(ev.payload || {}).join(",")}`
              );
              dispatch({ type: "session_event", event: ev });
            } else if (currentEventName === "snapshot_replay") {
              const atSeq = Number(parsed?.at_sequence_number || 0);
              console.log(`[useSession] SNAPSHOT-REPLAY session=${sidShort} at_seq=${atSeq}`);
              dispatch({
                type: "snapshot_replay",
                atSequence: atSeq,
                state: (parsed?.state || {}) as Record<string, any>,
              });
            } else if (currentEventName === "replay_start") {
              console.log(`[useSession] REPLAY-START session=${sidShort} count=${parsed?.count} since=${parsed?.since}`);
            } else if (currentEventName === "replay_end") {
              const ls = Number(parsed?.last_sequence || 0);
              console.log(`[useSession] REPLAY-END session=${sidShort} last_seq=${ls}`);
              dispatch({ type: "replay_end", lastSequence: ls });
            } else if (currentEventName === "stream_end") {
              const ls = Number(parsed?.last_sequence || 0);
              console.log(`[useSession] STREAM-END session=${sidShort} status=${parsed?.status} last_seq=${ls}`);
              dispatch({
                type: "stream_end",
                status: (parsed?.status || "completed") as SessionMaster["current_status"],
                lastSequence: ls,
              });
              try { await reader.cancel(); } catch { /* noop */ }
              return;
            } else if (currentEventName === "error") {
              console.error(`[useSession] STREAM-ERROR session=${sidShort}`, parsed);
              dispatch({ type: "error", error: String(parsed?.error || "stream error") });
            } else {
              console.log(`[useSession] STREAM unknown-frame session=${sidShort} name=${currentEventName}`);
            }
          }
        }
      } catch (err) {
        if ((err as any)?.name === "AbortError") {
          console.log(`[useSession] STREAM ABORTED session=${sidShort} (expected on unmount/resync)`);
          return;
        }
        console.error(`[useSession] STREAM EXC session=${sidShort}`, err);
        dispatch({ type: "error", error: String((err as Error).message || err) });
      }
    },
    [sessionId]
  );

  // ── Lifecycle: load master + start stream when sessionId changes ─────────
  useEffect(() => {
    if (!sessionId) {
      console.log("[useSession] MOUNT skipped (no sessionId)");
      return;
    }
    console.log(`[useSession] MOUNT session=${sessionId.slice(0, 8)}`);
    dispatch({ type: "loading" });
    fetchSession();
    streamEvents(0);
    return () => {
      console.log(`[useSession] UNMOUNT session=${sessionId.slice(0, 8)}`);
      try { abortRef.current?.abort(); } catch { /* noop */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // ── Gap-recovery: when reducer flags needsResync, restart stream ─────────
  useEffect(() => {
    if (!state.needsResync || !sessionId) return;
    const resyncFrom = Math.max(0, state.lastSequence - 10);
    console.warn(
      `[useSession] RESYNC session=${sessionId.slice(0, 8)} last_seq=${state.lastSequence} resync_from=${resyncFrom}`
    );
    try { abortRef.current?.abort(); } catch { /* noop */ }
    dispatch({ type: "reset_for_resync", resyncFrom });
    // Re-fetch master row too so current_phase is fresh
    fetchSession();
    streamEvents(resyncFrom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.needsResync]);

  // ── Actions ───────────────────────────────────────────────────────────────
  const resume = useCallback(
    async (gateId: string, actionName: string, payload: Record<string, any> = {}) => {
      const sidShort = (sessionId || "?").slice(0, 8);
      console.log(
        `[useSession] RESUME-CALL session=${sidShort} gate_id=${gateId} action=${actionName} payload_keys=${Object.keys(payload).join(",")}`
      );
      if (!sessionId) {
        console.warn("[useSession] RESUME-ABORT no sessionId");
        return { success: false, error: "no session" };
      }
      if (!gateId) {
        console.error("[useSession] RESUME-ABORT empty gate_id — refusing to POST");
        return { success: false, error: "empty gate_id" };
      }
      const gate_resolution_id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `grid-${Date.now()}-${Math.random().toString(36).slice(2)}`;

      const body = {
        gate_id: gateId,
        gate_resolution_id,
        action: actionName,
        payload,
      };
      console.log(`[useSession] RESUME-BODY session=${sidShort}`, body);

      try {
        const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/resume`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          credentials: "include",
          body: JSON.stringify(body),
        });
        console.log(`[useSession] RESUME-RESP session=${sidShort} status=${res.status}`);
        if (!res.ok) {
          const txt = await res.text();
          console.error(`[useSession] RESUME-FAIL session=${sidShort} status=${res.status} body=${txt}`);
          return { success: false, error: `resume failed (${res.status}): ${txt}` };
        }
        const json = await res.json().catch(() => ({}));
        console.log(`[useSession] RESUME-OK session=${sidShort}`, json);
        // The follow-up events will arrive via SSE; no need to merge here.
        return { success: true };
      } catch (err) {
        console.error(`[useSession] RESUME-EXC session=${sidShort}`, err);
        return { success: false, error: String((err as Error).message || err) };
      }
    },
    [sessionId]
  );

  const cancel = useCallback(
    async (reason: string = "user_cancelled") => {
      if (!sessionId) return { success: false, error: "no session" };
      try {
        const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          credentials: "include",
          body: JSON.stringify({ reason }),
        });
        if (!res.ok) {
          const txt = await res.text();
          return { success: false, error: `cancel failed (${res.status}): ${txt}` };
        }
        return { success: true };
      } catch (err) {
        return { success: false, error: String((err as Error).message || err) };
      }
    },
    [sessionId]
  );

  return {
    ...state,
    resume,
    cancel,
    refetchSession: fetchSession,
  };
}
