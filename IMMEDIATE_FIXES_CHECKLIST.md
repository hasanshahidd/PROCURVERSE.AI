# Immediate Fixes Checklist

Purpose: Must-fix items for internal sharing and stable development before production hardening.

## P0 - Fix First

1. Restore test collection and baseline test execution [DONE]
- Fix indentation error in backend/tests/test_compliance_agent.py line 176.
- Fix import path error in backend/tests/test_agent_logging.py line 21.
- Ensure pytest is available in active environment and tests can run.

2. Fix startup and runtime path mismatch [DONE]
- Align startup behavior in package.json line 11.
- Align static serving path in backend/main.py line 234 with build output in vite.config.ts line 19.

3. Resolve Python dependency conflicts [DONE]
- Fix conflicting package set in requirements.txt lines 11 and 13.
- Reconcile version drift with pyproject.toml line 8.

4. Make frontend type-checking real [DONE]
- Add proper TypeScript project config and make npm run check perform actual validation.

5. Fix direct query runtime bug [DONE]
- Add missing DB pool imports used by backend/routes/chat.py line 44.

## P1 - Do Next (before wider external exposure)

6. Lock down sensitive mutation endpoints [DONE]
- Add backend auth and authorization checks for approval and admin reset routes.

7. Tighten CORS policy [DONE]
- Reduce overly broad credentialed CORS policy in backend/main.py lines 133 to 136.

8. Fail fast on critical startup failures [DONE]
- Do not continue startup when DB pool init fails in backend/main.py lines 207 to 217.

9. Improve health signal accuracy [DONE]
- Include DB pool health in overall status in backend/routes/health.py line 25.

10. Complete human-in-the-loop TODO paths
- Implement pending TODOs in backend/routes/agentic.py lines 2171 and 2219.

## Execution order

- Day 1 to Day 2: Items 1, 2
- Day 3: Items 3, 4
- Day 4: Item 5 and re-run full checks
- Day 5+: P1 items

## Done criteria

- Tests collect and run successfully.
- App starts cleanly with consistent frontend-backend path behavior.
- No dependency conflict output from pip check.
- npm run check performs actual type validation.
- Critical runtime bug on /api/query is resolved.
