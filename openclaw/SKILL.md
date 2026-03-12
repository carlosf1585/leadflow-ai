# LeadFlow AI Skill for OpenClaw

## Setup
1. Copy to `~/.openclaw/skills/leadflow/SKILL.md`
2. Add to `~/.openclaw/openclaw.json`:
```json
{
  "skills": {
    "entries": {
      "leadflow": {
        "enabled": true,
        "env": {
          "LEADFLOW_API_URL": "https://your-app.up.railway.app",
          "LEADFLOW_ADMIN_TOKEN": "your-admin-token"
        }
      }
    }
  }
}
```

## Commands
| Say | Result |
|---|---|
| `revenue` | Daily $$ vs $180 goal |
| `add Miami to discovery` | Launch agents in Miami |
| `run sales sequences` | Trigger email follow-ups |
| `find new niches` | AI finds profitable niches |
| `launch campaigns for roofing` | Create ads + pages |
| `check queue depths` | Monitor all agent queues |

## How it works
OpenClaw calls POST `{LEADFLOW_API_URL}/api/admin/command`
with header `Authorization: Bearer {LEADFLOW_ADMIN_TOKEN}`
Body: `{"command": "<user intent>", "city": "...", "niche": "..."}`