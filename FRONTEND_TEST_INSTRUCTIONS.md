# Frontend AgentProcessVisualizer Test Instructions

## ✅ Backend Status: READY
- Backend running on http://localhost:5000
- Frontend running on http://localhost:5173
- 11 agents registered and operational
- SSE streaming endpoint verified (21 events sent)

## 🧪 Test the Fix (Manual Browser Test)

### Steps:
1. **Open browser** to http://localhost:5173

2. **Navigate to Agent Dashboard** (should be visible in sidebar menu)

3. **Scroll down** to "Agent Process Visualizer" section

4. **Open browser DevTools** (F12)
   - Go to **Console** tab
   - You should see logs like `[Event] received {...}`

5. **Click "Execute Test Agent"** button (default query already filled)

6. **Watch the animation carefully:**

### ✅ EXPECTED BEHAVIOR (With Fix):
- **NOT this** ❌: All 7 steps appear instantly/all at once
- **THIS** ✅: Steps appear **one-by-one** with visible **~700ms delays**
  
  **Timeline (~14.7 seconds total):**
  ```
  0.0s  → Step 1 appears (RECEIVED)
  0.7s  → Step 2 appears (CLASSIFYING)
  1.4s  → Step 3 appears (ROUTING)
  2.1s  → Step 4 appears (OBSERVING)
  2.8s  → Step 5 appears (DECIDING)
  3.5s  → Step 6 appears (ACTING)
  4.2s  → Step 7 appears (LEARNING)
  ...   → Additional sub-agent steps
  ~14.7s → Final "Execution Complete" card appears
  ```

7. **Check Console Logs:**
   - Should see `[Event] received`, `[Event] classifying`, etc. **immediately** (SSE stream)
   - But UI steps should **render sequentially** with delays (event queue processor)

8. **Verify interval doesn't terminate early:**
   - All 21 events should be visible on screen
   - No missing steps
   - "Execute Test Agent" button re-enabled only after last step visible

### 🐛 If Still Seeing Bulk Loading:
1. Hard refresh (Ctrl+Shift+R) to clear cache
2. Check browser console for errors
3. Verify no TypeScript compilation errors in terminal
4. Check Network tab → should see POST to `/api/agentic/execute/stream` with 21 SSE events

### 📊 What's Happening Behind the Scenes:
```
SSE Stream (instant)     Event Queue (700ms delays)     UI Display (sequential)
─────────────────────    ─────────────────────────      ───────────────────────
All 21 events arrive  →  pendingEventsRef queues     →  Step 1 renders
in ~500ms               them all immediately             ↓ 700ms delay
                                                         Step 2 renders
                        setInterval processes            ↓ 700ms delay
                        one event per tick               Step 3 renders
                                                         ↓ 700ms delay
                        isStreamDoneRef.current          ...
                        = true when 'complete'           ↓ 700ms delay
                        event arrives                     Step 21 renders
                                                         ↓
                        Queue drains completely          setIsExecuting(false)
                        THEN interval stops              Button re-enabled
```

### 🎯 The Fix That Was Applied:
1. **Added `isStreamDoneRef`** - tracks when stream ends (doesn't trigger re-render)
2. **Removed early `setIsExecuting(false)`** - no longer called in interval callback
3. **Added drain check** - only stops when `isStreamDoneRef.current && queue.length === 0`
4. **Decoupled lifecycle** - interval self-terminates after processing all events

This prevents React from destroying the interval before the queue finishes draining!

---

## 🔍 Alternative Quick Test (No Browser)
Run this PowerShell command to verify SSE events are sending:
```powershell
.\test_agent_streaming.ps1
```

Expected output: 21 events listed sequentially
