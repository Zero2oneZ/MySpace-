# Onboarding by SVG — The Viral Agent Invitation

> An SVG file is not just an image. It is a program, a wallet, and an invitation.
> When a user posts an SVG to X/Telegram/Discord, they are not sharing art — they are sharing an agent.

---

## The Concept

### What the user receives

A file named `clan-invite.svg` (or `tool-badge.svg`, `game-pass.svg`):

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"
     data-onboard="base64:eyJjbGFuX2lkIjoi..."
     data-payment="base64:eyJzdWlfaW50ZW50Ijoi..."
     data-agent="base64:eyJhZ2VudF9jb25maWciOiJ...">
  <rect width="400" height="200" fill="#050810" />
  <text x="50%" y="40%" fill="#2e7" font-family="monospace" font-size="24"
        text-anchor="middle">MySpace++ Clan</text>
  <text x="50%" y="60%" fill="#aaa" font-family="monospace" font-size="14"
        text-anchor="middle">Tap to join → Agent spawns automatically</text>
</svg>
```

### What happens when posted

1. **Social scraper** (Level 2 agent) detects the image upload via webhook
2. **SVG parser** (Level 1 agent) extracts `data-onboard`, `data-payment`, `data-agent`
3. **Wallet agent** (Level 3 agent) checks/creates a Sui wallet for the user
4. **Spawn agent** (Level 3 agent) writes a new task to ToDo-JobBoard: `T-XXX | onboard | ...`
5. **Welcome agent** (Level 2 agent) sends a DM: "Your agent is ready. Say 'hello' to start."

Total time: < 3 seconds.

---

## Technical Specification

### Data attributes

| Attribute | Encoded | Contains |
|-----------|---------|----------|
| `data-onboard` | base64 gzip JSON | `{clan_id, invitation_token, expiry}` |
| `data-payment` | base64 gzip JSON | `{sui_intent, amount_trolln, recipient}` |
| `data-agent` | base64 gzip JSON | `{agent_config, starting_stats, model_pref}` |
| `data-chain` | base64 gzip JSON | `{parent_task_id, correlation_id, crystal_hash}` |

### Encoding chain

```python
import json, gzip, base64

def encode_payload(data: dict) -> str:
    j = json.dumps(data, sort_keys=True)
    gz = gzip.compress(j.encode(), compresslevel=9)
    b64 = base64.urlsafe_b64encode(gz).decode().rstrip("=")
    return f"base64:{b64}"

def decode_payload(encoded: str) -> dict:
    b64 = encoded.replace("base64:", "")
    # pad
    pad = 4 - len(b64) % 4
    b64 += "=" * pad
    gz = base64.urlsafe_b64decode(b64)
    j = gzip.decompress(gz).decode()
    return json.loads(j)
```

### Size constraints

- Max attribute value: 4 KB (most social platforms truncate > 4KB inline)
- Typical compressed payload: 200-800 bytes
- SVG total size: 2-10 KB (well within all platform limits)

---

## Social Platform Detection

### Discord

Webhook on a channel watches for image uploads:

```python
# discord:read_messages polls the channel
# When an SVG attachment is found:
# 1. Download the SVG
# 2. Parse data-* attributes
# 3. Call agent spawn pipeline
```

### X (Twitter)

Harder — requires polling or paid API. Alternative: user DMs the SVG to a bot account.

### Telegram

Bot API `getUpdates` with `allowed_updates=["message"]`. Messages with document/photo:

```python
# telegram:upload sends the SVG
# Bot reads reply → detects file → parses → spawns
```

---

## Agent Spawn Pipeline

```
User posts SVG
    │
    ▼
┌──────────────┐
│ Social       │  Level 2 — detects post, downloads SVG
│ Listener     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ SVG Parser   │  Level 1 — extracts data-* attributes
│ (decode)     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Wallet Check │  Level 3 — Sui wallet exists? Create if not.
│ (Sui API)    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Agent Spawn  │  Level 3 — writes ToDo-JobBoard row
│ (chain_runner│  appends JSONL event
│  --spawn)    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Welcome Msg  │  Level 2 — sends DM with agent status
│ (social send)│
└──────────────┘
```

---

## Variants

### Tool Badge SVG

Instead of a clan invitation, the SVG contains a tool config:

```svg
<svg data-tool="base64:...">
  <text>MySpace++ Tool: Discord Summary Bot</text>
  <text>pip install myspace-discord-summary</text>
</svg>
```

Posting this = sharing the tool. The receiver gets an auto-generated install command.

### Game Pass SVG

Contains a matchmaking ticket:

```svg
<svg data-game="base64:...">
  <text>Match ID: #8821</text>
  <text>Stake: 0.5 TROLLN</text>
</svg>
```

Posting this = challenging someone to a match.

---

## Security Considerations

1. **Never execute SVG as code** — only parse `data-*` attributes
2. **Validate expiry** — invitations expire after 24h
3. **One-time use** — `invitation_token` is burned after first parse
4. **Rate limit** — max 5 spawns per IP per hour
5. **Human review** — Level 5 agent reviews spawn logs daily

---

## MVP Implementation

Phase 1 (Level 2):
- `discord:read_messages` detects SVG attachment
- Download + parse + extract
- Write spawn event to JSONL

Phase 2 (Level 3):
- Sui wallet auto-creation
- Payment intent processing
- Agent state initialization

Phase 3 (Level 4):
- Cross-platform detection (Telegram, X, WhatsApp)
- Viral tracking (who invited who)
- Reward distribution (referrer gets 10% of first action fee)

---

*ONBOARDING_SVG v0.1.0 | Viral agent invitation protocol | 2026-05-28*
