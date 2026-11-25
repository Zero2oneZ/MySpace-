# Agent Card: THIRD_PARTY_MANAGEMENT (`core/lib/third_party/`)

> **Scope:** `studio/third_party/` — outbound connectivity to Discord, Telegram, WhatsApp, Twitter/X, Facebook, and any future messaging platform.
> **Last updated:** 2026-05-28
> **Determinism:** every connection is a config file on disk; state transitions by `mv`; every send is append-only JSONL with crystal hash.

---

## 1. What This Does (One Paragraph)

A unified outbound connector layer for all external messaging and social platforms. Every service gets a deterministic config JSON under `studio/third_party/{service}/`. The `ThirdPartyManager` loads active configs, handles authentication, rate limits, message dispatch, and logs every send append-only. No scattered credentials. No ad-hoc API calls. One manager, one log, one chain of sends.

---

## 2. Directory Layout (Canonical)

```
studio/third_party/
├── discord/
│   └── vm_mspc_001.discord.connect.discord_bot.active.v0.json
├── telegram/
│   └── vm_mspc_001.telegram.connect.telegram_bot.active.v0.json
├── whatsapp/
│   └── vm_mspc_001.whatsapp.connect.whatsapp_business.active.v0.json
├── twitter/
├── facebook/
├── instagram/
├── slack/
├── messenger/
├── signal/
└── (any future service — add a directory, drop a config)
```

### Naming Convention (VM-CONSOLIDATION §9)

```
vm_mspc_001.{service}.{action}.{name}.{state}.{version}.json
```

- `service` = discord, telegram, whatsapp, twitter, facebook...
- `action` = connect, send, listen, webhook
- `name` = human-readable label (bot name, account name)
- `state` = active | paused | archived
- `version` = v0, v1, ...

**State transitions by `mv`:** `active` → `paused` → `archived`. Never mutate in place. Always move.

---

## 3. Supported Services

| Service | Dependency | Auth Fields | Notes |
|---|---|---|---|
| **Discord** | `pip install discord.py` | `bot_token`, `application_id` | Bot token from Discord Developer Portal |
| **Telegram** | `pip install python-telegram-bot` | `bot_token` | From @BotFather |
| **WhatsApp** | `requests` (stdlib ok) | `phone_id`, `access_token` | Meta Business API |
| **Twitter/X** | `pip install tweepy` | `bearer_token`, `consumer_key`, `consumer_secret`, `access_token`, `access_secret` | OAuth 1.0a |
| **Facebook** | `pip install facebook-sdk` | `access_token`, `page_id` | Graph API |

Missing dependencies → graceful stub. Logs the attempt but does not send.

---

## 4. Commands (Exact Usage)

### 4.1 Connect (Register a Service)

```bash
cc third_party-connect --service telegram --token "BOT_TOKEN_HERE" --name "my_bot" --tags "broadcast,alert"
cc third_party-connect --service discord --token "BOT_TOKEN_HERE" --name "discord_bot" --tags "dm,alert"
cc third_party-connect --service whatsapp --token "ACCESS_TOKEN" --name "wa_business"
```

Creates a config JSON in `studio/third_party/{service}/`. The manager loads it on next `cc third_party-status`.

---

### 4.2 Send a Message

```bash
cc third_party-send --service telegram --to "CHAT_ID" --message "Build complete"
cc third_party-send --service discord --to "CHANNEL_ID" --message "New deployment"
cc third_party-send --service twitter --to "tweet" --message "System status: green"
```

- `to` = chat_id (Telegram), channel_id (Discord), phone number (WhatsApp), `tweet` or user_id (Twitter), page_id (Facebook)
- Every send is logged to `~/.cc/third_party_logs/{service}_sends.jsonl`

---

### 4.3 List Connections

```bash
cc third_party-list                    # all services
cc third_party-list --service telegram # filter by service
cc third_party-list --state active     # filter by state
```

Output columns: `SERVICE`, `NAME`, `STATE`, `ASSET_ID`

---

### 4.4 Status

```bash
cc third_party-status
```

JSON dump: active configs per service, connected instances, totals.

---

### 4.5 Archive a Connection

```bash
cc third_party-archive --asset-id "vm_mspc_001.telegram.connect.my_bot.active.v0.json"
```

Moves file from `.active.` to `.archived.` on disk and reloads.

---

## 5. Python API

```python
from core.lib.third_party.manager import ThirdPartyManager
from core.lib.third_party.base import ConnectionConfig

mgr = ThirdPartyManager().load_all()

# Send to one service
results = mgr.send("telegram", "123456789", "Hello from cc")
for r in results:
    print(r.success, r.crystal_id)

# Broadcast by tag (sends to every active connector with matching tag)
results = mgr.send_by_tag("alert", "System alert: disk full")
for svc, res_list in results.items():
    print(svc, [r.success for r in res_list])

# Add a new config programmatically
cfg = ConnectionConfig(
    service="telegram",
    name="backup_bot",
    auth={"bot_token": "TOKEN"},
    routing_tags=["urgent", "backup"],
)
path = mgr.add_config(cfg)

# Health check
print(mgr.status())

# Disconnect everything gracefully
mgr.disconnect_all()
```

---

## 6. Integration Points

### Routing Operator (`core/lib/endpoints/router.py`)
- Inbound events (webhooks, bot messages) that need a **reply** route through the operator → `ThirdPartyManager.send()`
- `reply` and `broadcast` actions are the bridge between endpoints and third_party

### Inference Logger (`core/lib/inference_logger.py`)
- Model-generated alerts can trigger `cc third_party-send --service telegram ...`
- Every send has a crystal_id, so you can cross-reference: `cc inference-search "crystal_id:abc123"`

### Chat Gateway (`core/lib/chat.py`)
- `cc chat --godot` can emit packets that include `third_party_send` actions
- Tiny-tier slices can include exact coordinates for which service/channel to notify

### Godot Bridge (`studio/godot/project/src/cc_bridge.gd`)
- Receives `notify` actions from the engine → routes to `ThirdPartyManager`

---

## 7. Determinism Rules

1. **Config is the truth.** Credentials, rate limits, and tags live in the JSON file. Never hardcode in code.
2. **State transitions by `mv`.** Archive by renaming, never by editing `state` in place.
3. **Append-only sends log.** `~/.cc/third_party_logs/{service}_sends.jsonl` is never truncated.
4. **Graceful degradation.** Missing dependency = stub that logs but does not send. No crashes.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `discord.py_missing` | `pip install discord.py` |
| `telegram_lib_missing` | `pip install python-telegram-bot` |
| `tweepy_missing` | `pip install tweepy` |
| `facebook_sdk_missing` | `pip install facebook-sdk` |
| Send succeeds but nothing arrives | Check recipient ID (chat_id, channel_id, phone_id) |
| Rate limited | Adjust `limits.requests_per_minute` in config JSON |
| Token leaked in logs | Tokens are in config files only; send logs contain only previews |

---

## 9. Quick Reference (Cheatsheet)

```bash
# Register services
cc third_party-connect --service telegram --token "TOKEN" --name "bot" --tags "broadcast,alert"
cc third_party-connect --service discord --token "TOKEN" --name "bot" --tags "dm"

# Send
cc third_party-send --service telegram --to "CHAT_ID" --message "Hello"
cc third_party-send --service discord --to "CHANNEL_ID" --message "Hello"

# List & status
cc third_party-list
cc third_party-list --service telegram --state active
cc third_party-status

# Archive
cc third_party-archive --asset-id "vm_mspc_001.telegram.connect.bot.active.v0.json"

# Check logs
cat ~/.cc/third_party_logs/telegram_sends.jsonl | tail -5
```

---

**Card ID:** `agent-card:third_party_management-v1`
**Deterministic:** yes (configs on disk, state by mv, append-only logs)
**Required context:** `VM-CONSOLIDATION.md §9`, `studio/models/AGENT_CARD.md`
