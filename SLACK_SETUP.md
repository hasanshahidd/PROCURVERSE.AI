# Slack Integration Setup — Sprint 9

This guide walks you through connecting Procure AI to Slack so that approval
requests, payment alerts, and anomaly notifications are delivered directly to
your Slack workspace.

---

## Prerequisites

- A Slack workspace where you have permission to install apps
- The Procure AI backend deployed (or running locally) with a publicly reachable
  URL for the interactive webhook (ngrok is fine for local testing)

---

## Step 1 — Create a Slack App

1. Go to https://api.slack.com/apps and click **Create New App**.
2. Choose **From scratch**.
3. Give the app a name (e.g. *Procure AI*) and select your workspace.
4. Click **Create App**.

---

## Step 2 — Add Bot Token Scopes

1. In the left sidebar click **OAuth & Permissions**.
2. Under **Bot Token Scopes** click **Add an OAuth Scope** and add:
   - `chat:write` — post messages to channels
   - `channels:read` — list public channels
   - `im:write` — send direct messages to users
3. Optionally add `chat:write.public` if you want the bot to post to channels it
   has not been explicitly invited to.

---

## Step 3 — Enable Interactivity (Approval Buttons)

1. In the left sidebar click **Interactivity & Shortcuts**.
2. Toggle **Interactivity** to **On**.
3. Set the **Request URL** to:

   ```
   https://your-domain.com/api/agentic/slack/interactive
   ```

   Replace `your-domain.com` with your actual public hostname.
   For local development use an ngrok URL, e.g.:

   ```
   https://abc123.ngrok.io/api/agentic/slack/interactive
   ```

4. Click **Save Changes**.

---

## Step 4 — Install the App to Your Workspace

1. In the left sidebar click **Install App**.
2. Click **Install to Workspace** and authorise the requested permissions.
3. After installation you will see a **Bot User OAuth Token** starting with `xoxb-`.

---

## Step 5 — Copy Credentials to Environment Variables

Open (or create) your `.env` file and set:

```dotenv
# Slack integration (Sprint 9)
SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
SLACK_APPROVAL_CHANNEL=#procurement-approvals
SLACK_FINANCE_CHANNEL=#finance-alerts
```

Where to find each value:

| Variable | Location in Slack App dashboard |
|---|---|
| `SLACK_BOT_TOKEN` | OAuth & Permissions → Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | Basic Information → App Credentials → Signing Secret |

Invite the bot to the channels it needs to post in:

```
/invite @ProcureAI
```

---

## Step 6 — Verify the Integration

Restart the Procure AI backend, then run:

```bash
curl http://localhost:5000/api/agentic/slack/status
```

Expected response when fully configured:

```json
{
  "slack_enabled": true,
  "bot_token_configured": true,
  "approval_channel": "#procurement-approvals",
  "mode": "live"
}
```

---

## Step 7 — Send a Test Notification

```bash
curl -X POST http://localhost:5000/api/agentic/slack/notify \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "approval_request",
    "payload": {
      "pr_number": "PR-TEST-001",
      "description": "Test laptop purchase",
      "budget": 25000,
      "department": "IT",
      "requester": "Test User",
      "priority": "medium"
    }
  }'
```

A message with Approve / Reject buttons should appear in `#procurement-approvals`.

---

## Demo Mode (SLACK_ENABLED=false)

When `SLACK_ENABLED=false` (the default), no real Slack API calls are made.
All notifications are logged to the application logger at INFO level, so you
can verify the message content without needing a Slack workspace.

---

## Endpoints Added (Sprint 9)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agentic/slack/status` | Check configuration and mode |
| `POST` | `/api/agentic/slack/notify` | Send a notification (approval / payment / anomaly) |
| `POST` | `/api/agentic/slack/interactive` | Receive button-click callbacks from Slack |

---

## Troubleshooting

**Bot posts to the wrong channel**
Make sure `SLACK_APPROVAL_CHANNEL` and `SLACK_FINANCE_CHANNEL` are set correctly
and that the bot has been invited to those channels.

**"not_in_channel" error from Slack API**
Invite the bot: `/invite @YourAppName` inside the target channel.

**Signature verification fails (401)**
Ensure `SLACK_SIGNING_SECRET` matches the value in Basic Information → App Credentials.
Also check that your server clock is in sync (Slack rejects requests older than 5 minutes).

**Buttons do not update the message**
Confirm the Interactivity Request URL is reachable from the public internet and
that the path is exactly `/api/agentic/slack/interactive`.
