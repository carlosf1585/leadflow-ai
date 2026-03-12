# LeadFlow AI v3

Automated AI-powered lead generation SaaS — 11 AI agents, FastAPI, PostgreSQL, Redis, Stripe, OpenAI GPT-4.

## Architecture
11 autonomous agents handle the full pipeline: discover businesses on Google Maps, send personalized outreach emails, qualify leads with AI, route leads by GPS, charge businesses via Stripe, and track revenue — all without manual intervention.

## Railway Deployment — Step by Step

### 1. Create services in Railway dashboard
- API service (this repo)
- PostgreSQL plugin
- Redis plugin
- One service per agent (copy repo, change start command)

### 2. Set environment variables
Copy .env.example values into Railway Variables tab.

### 3. Agent start commands
| Service | Start Command |
|---|---|
| api | uvicorn app.main:app --host 0.0.0.0 --port $PORT |
| scheduler | python scheduler/cron.py |
| agent-discovery | python -m agents.discovery_agent |
| agent-outreach | python -m agents.outreach_agent |
| agent-qualify | python -m agents.qualify_agent |
| agent-routing | python -m agents.routing_agent |
| agent-billing | python -m agents.billing_agent |
| agent-analytics | python -m agents.analytics_agent |
| agent-niche | python -m agents.niche_agent |
| agent-sales | python -m agents.sales_agent |
| agent-landing | python -m agents.landing_agent |
| agent-campaign | python -m agents.campaign_agent |

### 4. API Endpoints
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /api/leads/submit | Public | Submit consumer lead |
| POST | /api/businesses/register | Public | Register business |
| POST | /api/businesses/login | Public | Login |
| GET | /api/businesses/dashboard | JWT | Dashboard |
| GET | /api/leads/my-leads | JWT | Assigned leads |
| POST | /api/billing/setup-intent | JWT | Stripe card setup |
| POST | /api/billing/subscribe | JWT | Monthly plan |
| POST | /api/webhooks/stripe | Stripe | Events |
| POST | /api/admin/command | Admin | OpenClaw control |
| GET | /api/admin/stats | Admin | Revenue stats |
| GET | /health | Public | Health check |