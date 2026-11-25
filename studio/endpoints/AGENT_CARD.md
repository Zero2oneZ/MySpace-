# Agent Card: ENDPOINTS (`core/lib/endpoints/`)

> **Scope:** `studio/endpoints/` — inbound API listeners, webhook receivers, and the routing operator that connects external events to internal actions.
> **Last updated:** 2026-05-28
> **Determinism:** every endpoint and route is a config file on disk; state transitions by `mv`; every inbound event is append-only JSONL with crystal hash.

---

## 1. What This Does (One Paragraph)

A unified inbound gateway layer for external services to connect INTO the MySpace++ environment. Webhooks, REST APIs, Telegram bot webhooks, and Discord bot gateways are all config-driven listeners under `studio/endpoints/{kind}/`. Every inbound event is logged, matched against routing rules in `studio/endpoints/routes/`, and dispatched to internal handlers or outbound third_party connectors. One registry, one router, one audit trail.

---

## 2. Directory Layout (Canonical)

```
studio/endpoints/
├── registry.json                     # SINGLE SOURCE OF TRUTH (auto-generated)
├── webhook/
│   └── vm_mspc_001.webhook.generic.build_webhook.active.v0.json
├── rest/
│   └── vm_mspc_001.rest.generic.api_gateway.active.v0.json
├── discord_bot/
├── telegram_bot/
├── whatsapp_bot/
├── mcp_bridge/
└── routes/
    ├── vm_mspc_001.route.build_notify.active.v0.json
    └── vm_mspc_001.route.dm_reply.active.v0.json
```

### Naming Convention (VM-CONSOLIDATION §9)

**Endpoints:**
```
vm_mspc_001.{kind}.{service}.{name}.{state}.{version}.json
```

**Route Rules:**
```
vm_mspc_001.route.{name}.{state}.{version}.json
```

**State transitions by `mv`:** `active` → `paused` → `archived`. Never mutate. Always move.

---

## 3. Supported Listener Kinds

| Kind | Description | Default Port | Auth |
|---|---|---|---|
| **webhook** | Generic HTTP POST receiver | 9000 | `X-Webhook-Secret` header |
| **rest** | Minimal REST API gateway (GET/POST) | 9001 | Bearer token + IP whitelist |
| **discord_bot** | Discord bot gateway (requires discord.py) | N/A | Bot token |
| **telegram_bot** | Telegram webhook/polling | N/A | Bot token |
| **mcp_bridge** | MCP tool bridge for external tool calls | N/A | Sigil-based permissions |

---

## 4. Commands (Exact Usage)

### 4.1 Register an Endpoint

```bash
cc endpoint-start --kind webhook --name "build_webhook" --port 9000 --path "/webhook/build"
cc endpoint-start --kind rest --name "api_gateway" --port 9001 --path "/api/v1"
```

Creates a config JSON. To actually start the listener process, run the corresponding Python module.

---

### 4.2 List Endpoints

```bash
cc endpoint-list                           # all
cc endpoint-list --kind webhook          # filter by kind
cc endpoint-list --service generic       # filter by service
cc endpoint-list --state active          # filter by state
cc endpoint-list --tag build_complete    # filter by routing tag
```

Output columns: `KIND`, `SERVICE`, `NAME`, `STATE`, `PATH`

---

### 4.3 Endpoint Status

```bash
cc endpoint-status
cc endpoint-status --kind webhook
```

JSON dump: active endpoints, counts, health.

---

### 4.4 Sync Registry

```bash
cc endpoint-sync
```

Rebuild `registry.json` by scanning all config files on disk. Run after manual edits or git pulls.

---

## 5. Routing (The Operator)

### 5.1 What Routing Does

When an inbound event arrives, the `RoutingOperator` evaluates rules in priority order (lowest first). The first matching rule's action is executed. Actions:

| Action | What Happens |
|---|---|
| `log` | Write to `~/.cc/routing_logs/route_decisions.jsonl` |
| `forward` | Pass event to another internal handler |
| `reply` | Send response back via third_party connector |
| `broadcast` | Send to ALL connectors with matching tag |
| `notify` | Emit desktop/terminal notification |
| `chain` | Run a `cc` command (e.g. `cc chat --tier tiny`) |

### 5.2 Add a Route Rule

```bash
cc route-add \
  --name "build_notify" \
  --priority 0 \
  --match-kind webhook \
  --match-service generic \
  --match-tag build_complete \
  --match-condition "body.get('status') == 'success'" \
  --action broadcast \
  --target build_notify \
  --template "Build {{body.project}} completed. Result: {{body.status}}"
```

### 5.3 List Route Rules

```bash
cc route-list
cc route-list --tag build_complete
```

Output columns: `PRIORITY`, `ACTION`, `MATCH`, `TARGET`

### 5.4 Test a Route

```bash
cc route-test --event-json '{"tag":"build_complete","body":{"project":"gently","status":"success","host":"z21"}}'
```

Prints which rules matched and what actions would execute. Safe — does not actually send.

### 5.5 Archive a Route

```bash
cc route-archive --asset-id "vm_mspc_001.route.build_notify.active.v0.json"
```

---

## 6. Python API

```python
from core.lib.endpoints.registry import EndpointRegistry
from core.lib.endpoints.router import RoutingOperator, RouteRule
from core.lib.endpoints.base import EndpointConfig, ReceiveEvent

# Registry
reg = EndpointRegistry()
reg.sync()
print(reg.list(kind="webhook", state="active"))

# Routing
op = RoutingOperator().load_rules()

# Simulate an event
import hashlib, json, time
event = ReceiveEvent(
    crystal_id=hashlib.sha256(b"test").hexdigest(),
    endpoint_asset_id="test",
    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    source_ip="127.0.0.1",
    headers={},
    body={"project": "gently", "status": "success"},
    tag="build_complete",
)
results = op.route(event)
print(results)

# Add a rule
rule = RouteRule(
    name="alert_on_failure",
    priority=1,
    match_kind="webhook",
    match_tag="build_complete",
    match_condition="body.get('status') == 'failure'",
    action="broadcast",
    target_service="urgent",
    template="BUILD FAILED: {{body.project}} on {{body.host}}",
)
path = op.add_rule(rule)
```

---

## 7. Integration Points

### ThirdPartyManager (`core/lib/third_party/manager.py`)
- `reply` and `broadcast` actions call `ThirdPartyManager.send()` and `send_by_tag()`
- This is the bridge: inbound webhook → route rule → outbound Telegram/Discord message

### Inference Logger (`core/lib/inference_logger.py`)
- Route decisions are logged to `~/.cc/routing_logs/route_decisions.jsonl`
- Each decision references the event's `crystal_id`, so you can trace full request lifecycle

### Chat Gateway (`core/lib/chat.py`)
- `chain` action can trigger `cc chat --tier tiny` with the inbound event as context
- Enables agentic responses to external webhooks

### MCP Tools (`studio/proxy/claude_proxy.py`)
- `mcp_bridge` endpoints expose internal tools to external MCP callers
- Auth via `db/schema/006_mcp.sql` tool_permissions rows (same as GentlyOS)

---

## 8. Determinism Rules

1. **Config is the truth.** Bind, auth, and routing live in the JSON file. Never hardcode ports or secrets.
2. **Rules are evaluated in priority order.** Lower priority number = evaluated first. First match wins.
3. **State transitions by `mv`.** Archive by renaming, never by editing in place.
4. **Append-only event logs.** `~/.cc/endpoint_logs/` and `~/.cc/routing_logs/` are never truncated.
5. **Template substitution is deterministic.** Same body + same template = same output, every time.

---

## 9. Security Notes

- **Whitelist IPs** in `auth.whitelist_ips` for REST endpoints
- **Secret headers** for webhooks: always set `X-Webhook-Secret` and verify on receive
- **Rate limits** in `limits.rate_limit` — defaults are generous (100 req/min), tighten for production
- **Never commit tokens.** Config files contain secrets; add `studio/endpoints/**/*.json` to `.gitignore` (or keep them in `studio/auth/`)

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `Port already in use` | Change `bind.port` in config or stop the existing listener |
| `Webhook returns 404` | Verify `path` in config matches POST path exactly |
| `Route not matching` | Check `match_tag` and `match_condition` syntax; use `cc route-test` |
| `No outbound send on match` | Verify third_party connector is active: `cc third_party-status` |
| `registry.json stale` | Run `cc endpoint-sync` |
| `Template not substituting` | Use `{{body.field_name}}` syntax; field must exist in event body |
| `IP blocked` | Add your IP to `auth.whitelist_ips` in the REST config |

---

## 11. Quick Reference (Cheatsheet)

```bash
# Register endpoints
cc endpoint-start --kind webhook --name "build_webhook" --port 9000 --path "/webhook/build"
cc endpoint-start --kind rest --name "api_gateway" --port 9001 --path "/api/v1"

# List & status
cc endpoint-list
cc endpoint-list --kind webhook --state active
cc endpoint-status
cc endpoint-sync

# Routing
cc route-add --name "build_notify" --priority 0 --match-kind webhook --match-tag build_complete --action broadcast --target build_notify --template "Build done: {{body.project}}"
cc route-list
cc route-test --event-json '{"tag":"build_complete","body":{"project":"gently","status":"success"}}'
cc route-archive --asset-id "vm_mspc_001.route.build_notify.active.v0.json"

# Check logs
cat ~/.cc/endpoint_logs/webhook_generic_events.jsonl | tail -5
cat ~/.cc/routing_logs/route_decisions.jsonl | tail -5
```

---

**Card ID:** `agent-card:endpoints-v1`
**Deterministic:** yes (configs on disk, state by mv, append-only logs, priority-ordered rules)
**Required context:** `VM-CONSOLIDATION.md §9`, `studio/third_party/AGENT_CARD.md`
