# Airbyte Agents research (verified against PyPI wheels, 2026-11-20)

Sources: https://pypi.org/project/airbyte-agent-gmail/ ; https://pypi.org/project/airbyte-agent-sdk/ ; https://pypi.org/project/airbyte-agent-mcp/ ; https://github.com/airbytehq/airbyte-agent-connectors ; https://github.com/airbytehq/airbyte-agent-sdk ; https://docs.airbyte.com/ai-agents (thin; docs pages mostly did not render via fetch). Package contents were inspected directly (pip download + unzip).

## KEY TAKEAWAYS
- NO Google Calendar connector exists (`airbyte-agent-google-calendar` not on PyPI; Gmail README lists Calendar as unsupported). No Outlook/Microsoft, Todoist, or Zoom either. Plan Calendar via Google API directly.
- Gmail has real write actions (send, draft, label/archive, trash). Slack can post messages. Linear/Jira can create/update issues.
- NEW unified package: `airbyte-agent-sdk` (0.1.403, Python >=3.11) bundles 60+ connectors under `airbyte_agent_sdk.connectors.<name>`. Prefer it. The standalone `airbyte-agent-<x>` packages require Python >=3.13 (Gmail wheel: Requires-Python >=3.13) -- check your Python version first.
- Legacy `airbyte-ai-*` packages (asana, github, gong, greenhouse, hubspot, jira, linear, salesforce, stripe, zendesk-support) are the old naming; ignore.

## 1. Connectors (PyPI `airbyte-agent-*`, complete list from PyPI simple index)
Infra: `airbyte-agent-sdk`, `airbyte-agent-mcp` (MCP server / `agent-engine` CLI).
PERSONAL-RELEVANT (bold = recommended):
- **airbyte-agent-gmail** (0.1.31)
- **airbyte-agent-google-drive** (0.1.102)
- **airbyte-agent-slack** (0.1.96)
- **airbyte-agent-notion** (0.1.35)
- **airbyte-agent-github** (0.18.134)
- **airbyte-agent-linear** (0.19.134)
- **airbyte-agent-jira** (0.1.122)
- **airbyte-agent-asana** (0.19.136)
- airbyte-agent-hubspot (0.15.135), airbyte-agent-stripe (0.5.130), airbyte-agent-monday, airbyte-agent-clickup-api, airbyte-agent-confluence, airbyte-agent-airtable, airbyte-agent-granola (meeting notes), airbyte-agent-gitlab, airbyte-agent-typeform, airbyte-agent-twilio, airbyte-agent-zoho-crm
Not personal-relevant (business/ads/support): amazon-ads, amazon-seller-partner, amplitude, ashby, chargebee, facebook-marketing, freshdesk, gong, google-ads, google-analytics-data-api, google-search-console, greenhouse, harvest, incident-io, intercom, klaviyo, linkedin-ads, mailchimp, orb, paypal-transaction, pinterest, pylon, salesforce, sendgrid, sentry, shopify, snapchat-marketing, tiktok-marketing, woocommerce, zendesk-chat, zendesk-support, zendesk-talk.
Extra only inside airbyte-agent-sdk (no standalone pkg seen): customer_io, exa, outreach, reddit_ads, snowflake.
MISSING: google-calendar, outlook/microsoft, todoist, zoom, trello, dropbox.

## 2. Entities / actions / auth (OSS-mode auth class)
- Gmail (GmailAuthConfig: access_token(opt), refresh_token, client_id, client_secret): Profile get; Messages list/get/**create(send; raw base64url RFC2822, optional thread_id)**/**update(add_label_ids/remove_label_ids = archive/mark read)**; Messages Trash create / Untrash create; Labels list/create/get/update/delete; Drafts list/create/get/update/delete; Drafts Send create(id); Threads list/get. No attachments, forwarding, filters.
- Slack (SlackTokenAuthenticationAuthConfig: api_token xoxb-/xoxp-): Users list/get; Channels list/get/create/update; Channel Messages list; Threads list; **Messages create/update**; Channel Topics/Purposes create; Reactions create.
- Google Drive (OAuth config, same shape as Gmail): Files list/get/create/update/delete/download; Files Upload create; Files Export download; Drives, Permissions, Comments, Replies, Revisions, Changes list/get; About get.
- Notion (NotionAccessTokenAuthConfig: token ntn_/secret_): READ ONLY: Users, Pages, Data Sources, Blocks (list/get), Comments list.
- GitHub (GithubPersonalAccessTokenAuthConfig: token): READ ONLY, 24 entities (Issues, Pull Requests, Repos, Commits, Notifications-like Viewer, Discussions, Projects...) with list/get/api_search.
- Linear (LinearAuthConfig: api_key): Issues list/get/**create/update**; Comments list/get/**create/update**; Projects, Teams, Workflow States, Users list/get.
- Jira (JiraAuthConfig: username=email, password=API token): Issues api_search/**create**/get/**update**/delete; Issue Comments CRUD; Projects, Users, Issue Fields, Worklogs read; Issues Assignee update.
- Asana (AsanaPersonalAccessTokenAuthConfig: token): READ ONLY: Tasks, Projects, Workspaces, Users, Teams, Sections, Tags, Attachments, Subtasks, Dependencies.
- (Also HubSpot read+search; Stripe customers/products CRUD, refunds create.)
Several entities also list `context_store_search` (hosted only; local executor raises NotImplementedError) and `api_search` (native API search).

Auth modes: (a) OSS/local: you pass raw creds (OAuth client_id/secret/refresh_token for Google; PAT/API key for others); SDK calls third-party API directly. (b) Hosted: `AirbyteAuthConfig(customer_name, airbyte_client_id, airbyte_client_secret, organization_id optional)`; creds stored in Airbyte Cloud, enables Context Store search. Same connector class either way.

## 3. Python usage (verified signatures from wheel; not executed live, needs creds)
```python
# pip/uv: uv pip install airbyte-agent-sdk   (py>=3.11)  OR  airbyte-agent-gmail (py>=3.13)
import asyncio, base64, os
from email.message import EmailMessage
from airbyte_agent_sdk.connectors.gmail import GmailConnector, GmailAuthConfig
# standalone: from airbyte_agent_gmail import GmailConnector; from airbyte_agent_gmail.models import GmailAuthConfig

gmail = GmailConnector(auth_config=GmailAuthConfig(
    refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"]))   # access_token optional

async def main():
    lst = await gmail.execute("messages", "list", {"q": "is:unread newer_than:1d", "max_results": 20})
    msg = await gmail.execute("messages", "get", {"message_id": "<id>", "format": "full"})
    # archive:
    await gmail.execute("messages", "update", {"message_id": "<id>", "remove_label_ids": ["INBOX"]})
    # send:
    m = EmailMessage(); m["To"]="a@b.com"; m["Subject"]="Hi"; m.set_content("body")
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    await gmail.execute("messages", "create", {"raw": raw})
    # draft: ("drafts","create",{"message":{"raw":raw}})  ; send draft: ("drafts_send","create",{"id":draft_id})
    # trash: ("messages_trash","create",{"message_id": id})
asyncio.run(main())
```
Result objects: typed pydantic; SDK docs use `result.data if hasattr(result,"data") else result`. Entity names are snake_case of the table names (e.g. `drafts_send`, `messages_trash`) -- confirm with `await gmail.inspect_connector()`/ `GmailConnector` overloads if an entity errors.

Slack:
```python
from airbyte_agent_sdk.connectors.slack import SlackConnector, SlackTokenAuthenticationAuthConfig
slack = SlackConnector(auth_config=SlackTokenAuthenticationAuthConfig(api_token=os.environ["SLACK_TOKEN"]))
chs  = await slack.execute("channels","list",{"limit":50,"types":"public_channel,private_channel"})
hist = await slack.execute("channel_messages","list",{"channel":"C123","limit":50,"oldest":"1730000000"})
await slack.execute("messages","create",{"channel":"C123","text":"hello","thread_ts":"..."})
```
Hosted: `GmailConnector(auth_config=AirbyteAuthConfig(customer_name="me", airbyte_client_id=..., airbyte_client_secret=..., organization_id=...))` (import AirbyteAuthConfig from the connector package or `airbyte_agent_sdk.types`).

LLM tool wrapping (current recommended): `from airbyte_agent_sdk import build_connector_tools; tools = build_connector_tools(gmail, framework="pydantic_ai")` (also langchain, openai_agents, fastmcp); one connector per agent, or `@GmailConnector.agent_tool(...)` for multi-connector. `@Connector.tool_utils` is deprecated. Tools: inspect_connector, read_skill_docs, execute. `internal_retries=N` retries 429/5xx; output >100KB is rejected to the model.

## 4. MCP / Context Store / pricing
- Local MCP: `pip install airbyte-agent-mcp` (py>=3.13; deps fastmcp, pydantic-ai). CLI `agent-engine`: `uv run agent-engine connectors list-oss`; `connectors configure --package airbyte-agent-gmail` -> yaml; put creds in .env; `agent-engine mcp add-to claude-code|claude-desktop|cursor|codex <yaml>`; `agent-engine login <org-id>` for cloud creds. YAML: `connector: {package: airbyte-agent-gmail}` + `credentials: {...: ${env.VAR}}` (local) or `connector: {connector_id: ...}` + airbyte_client_id/secret (cloud). Aggregate yaml with `configs:` for multiple connectors. Local mode = only API-native list/get, no arbitrary search.
- Hosted Airbyte MCP: https://mcp.airbyte.com/mcp (Airbyte Cloud account; gives search/context-store queries over synced+indexed data; `context_store_search` / `context_store_sql_query` actions work only hosted).
- Cloud signup: https://cloud.airbyte.com/signup ; docs say 14-day free trial, no card. No hackathon credits found; ask Airbyte sponsors at the event. Skills: `npx skills add airbytehq/airbyte-agent-sdk`.
- Licensing: Elastic-2.0, status Alpha.

## 5. Gotchas
- Python >=3.13 for standalone connector wheels and airbyte-agent-mcp; sdk bundle works on 3.11+. Check env first.
- Gmail OAuth: you must create Google Cloud OAuth client, enable Gmail API, obtain refresh token (use OAuth Playground; test-mode apps need your account added as test user; sensitive scopes gmail.modify/send). Budget 15-30 min; do it early. Refresh tokens for unverified test apps expire in 7 days (fine for hackathon). Pass `on_token_refresh` callback to persist new tokens.
- No Calendar connector: use google-api-python-client with same OAuth client (add calendar scope) -- request all scopes (gmail.modify, calendar, drive.readonly) in one consent flow.
- Send/draft need hand-built base64url RFC2822 `raw`; no attachments.
- Notion/GitHub/Asana connectors are read-only; use for ingestion only. Writes available: Gmail, Slack, Linear, Jira, Drive, Stripe.
- Pagination via page_token/cursor; no built-in rate limiting beyond optional internal_retries; Gmail/Slack API quotas apply.
- Versions move fast (daily releases); pin versions. Docs site pages for AI agents were thin/unfetchable; PyPI READMEs/REFERENCE.md are the reliable source.
- Local mode has no "sync into a store" -- for Cognee ingestion you page through list/get yourself (Airbyte Context Store is hosted-only).
