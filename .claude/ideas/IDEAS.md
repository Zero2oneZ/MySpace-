# IDEAS Database — Agent Chain Strategic Inventory

> Append-only. Every idea gets an ID, a complexity score, a target cycle, and a status.
> Ideas are not tasks until they graduate. Graduation = complexity > 50 + agent chain routes to Level 4+.

## Format

Each idea lives as a JSONL row in `ideas.jsonl` and a human-readable block in this file.

```json
{"id": "IDEA-001", "title": "...", "complexity": 45, "target_cycle": "social_clan",
 "status": "draft", "created": "2026-05-28T16:00:00Z", "tags": ["game", "mcp", "unreal"],
 "case_use": "User tweets an SVG → onboards to AI clan", "revenue_model": "per-post micro-fee",
 "agent_benefit": "Engagement data trains prediction model"}
```

## Cycles (the larger systems ideas feed into)

| Cycle ID | What it is | Current status |
|---|---|---|
| `social_clan` | Social media clan where agents are controlled by posts/engagement | IDEA stage |
| `game_platform` | Launch games that handle AI + payment | IDEA stage |
| `unreal_toolbelt` | UE toolkit with real-world effects via MCP | IDEA stage |
| `onboarding_svg` | Tweet/post an SVG to onboard a chat/agent | IDEA stage |
| `mcp_tool_designer` | Auto-build MCP tools → hand user npm/SVG artifact | IDEA stage |
| `agent_feedback_loop` | Agents predict case use from engagement data | IDEA stage |
| `payment_router` | Per-action micro-payment across all platforms | IDEA stage |
| `deterministic_chain` | The .claude/ chain runner itself | IMPLEMENTED |

## Ideas

### IDEA-001 — Social Media Clan (agents controlled by engagement)

**Case use:** A user joins a "clan" on X/Telegram/Discord. Their posts and likes directly control an agent's behavior stats (strength, creativity, aggression, loyalty). The agent then acts on their behalf — posting, trading, creating content.

**Why it benefits a larger cycle:** Engagement data trains the `agent_feedback_loop` prediction model. The clan becomes a living dataset.

**Agent chain fit:** Level 3 (medium) for real-time engagement parsing. Level 4 (large) for agent behavior model updates. Level 5 (opus) for new clan mechanics.

**Revenue:** Per-post micro-fee (burns TROLLN). Agent upgrades (cosmetic + functional) purchased with zNiXz.

**MCP tools needed:**
- `social:engagement_score` (reads likes/replies)
- `agent:update_stats` (mutates agent state)
- `clan:leaderboard` (reads clan ranking)

**Status:** `draft`

---

### IDEA-002 — Game Platform (AI + payment in one launch)

**Case use:** User launches a game from our endpoint. The game:
1. Runs AI opponents via `hf:text_generation` (strategy prompts)
2. Handles payment via `payment_router` (per-match micro-fee)
3. Streams gameplay via `livepeer:create_stream`
4. Agents moderate the chat via `discord:read_messages` + `discord:send_message`

**Why it benefits a larger cycle:** Games are the highest-engagement onboarding path. A user who plays 10 matches is 50x more likely to use the MCP toolkit for their own project.

**Agent chain fit:** Level 4 for game architecture. Level 3 for matchmaking AI. Level 2 for payment reconciliation. Level 1 for health-check pings.

**Revenue:** Match fee (10% to platform, 90% to winner pool). Cosmetic NFTs on Sui.

**Status:** `draft`

---

### IDEA-003 — UNREAL Engine Toolbelt (real-world effects)

**Case use:** UE developer installs our plugin. Inside UE Blueprints, they can:
- Call `hf:image_generation` to generate textures from prompts
- Call `livepeer:create_stream` to broadcast gameplay
- Call `social:upload` to auto-post level completions
- Call `trollz:search_agents` to find AI teammates

**Why it benefits a larger cycle:** UE is the dominant 3D engine. Our tools inside UE = our tools inside every AAA/AA/indie project. The plugin acts as a trojan horse for the full MCP bridge.

**Agent chain fit:** Level 4 for plugin architecture. Level 3 for Blueprint node design. Level 2 for API wrapper generation.

**Onboarding artifact:** A single `.zip` containing the plugin + a sample level that generates a texture and tweets it. Developer posts the screenshot → viral loop.

**Status:** `draft`

---

### IDEA-004 — Onboarding by SVG (tweet to join)

**Case use:** A user receives an SVG file. They post it to X/Telegram. The SVG contains:
- A `data-onboard` attribute with a base64-encoded agent invitation
- A `data-payment` attribute with a Sui payment intent
- A visual representation of the clan/agent they're joining

When posted, our webhook (via `discord:read_messages` or social scraper) detects the SVG, decodes the invitation, and spawns an agent for the user.

**Why it benefits a larger cycle:** Zero-friction onboarding. No app download, no wallet setup (handled in background). The SVG IS the application.

**Agent chain fit:** Level 2 for SVG parsing/decoding. Level 3 for agent spawn + wallet creation. Level 5 for security review of the decode pipeline.

**Status:** `draft`

---

### IDEA-005 — MCP Tool Designer (auto-build → hand to user)

**Case use:** User describes a tool: "I want a Discord bot that reads my server and posts daily summaries to Telegram." The agent chain:
1. Level 4: Designs the tool architecture (which MCP tools to compose)
2. Level 3: Writes the implementation (Python/TypeScript)
3. Level 2: Packages it as `npm publish`-able or single-file script
4. Level 1: Generates an SVG badge showing the tool's status

The user receives:
- An `npm install myspace-tool-xyz` command
- Or a single `tool.py` they run
- Or an SVG they embed in their website

**Why it benefits a larger cycle:** Every tool designed is a new entry in the TrollzDotFun agent registry. The registry grows organically. Users become contributors.

**Agent chain fit:** Level 4 for design. Level 3 for implementation. Level 2 for packaging. Level 1 for badge generation.

**Status:** `draft`

---

### IDEA-006 — Agent Feedback Loop (predict case use)

**Case use:** After every agent action (tool call, social post, game move), the agent:
1. Logs the action + outcome to `ideas.jsonl`
2. Runs `model_router.py` on the next predicted task
3. Adjusts its own complexity thresholds based on success rate
4. If error rate > 30%, escalates to next level automatically

**Why it benefits a larger cycle:** This is the learning layer. Without it, the chain is static. With it, the chain evolves.

**Agent chain fit:** Meta — this runs AT the chain level, not inside a task. The chain_runner itself becomes an agent.

**Status:** `design`

---

### IDEA-007 — Payment Router (per-action micro-fee)

**Case use:** Every tool call has an implicit cost:
- `hf:text_generation` → 0.001 TROLLN per 1k tokens
- `livepeer:create_stream` → 0.1 TROLLN per hour
- `social:upload` → 0.01 TROLLN per post
- `trollz:search_agents` → free (onboarding hook)

The payment router:
1. Estimates cost before execution
2. Checks wallet balance via Sui
3. Burns TROLLN or charges fiat
4. Records the transaction in the crystal chain

**Why it benefits a larger cycle:** Revenue sustains infrastructure. The payment data is also training data for the `agent_feedback_loop`.

**Agent chain fit:** Level 3 for cost estimation. Level 4 for wallet integration. Level 5 for financial compliance.

**Status:** `draft`

---

## Graduation Rules

An idea graduates from `draft` → `design` → `planned` → `task` when:
1. **Complexity > 50** — requires Level 4+ agent involvement
2. **Case use is concrete** — a single user journey is fully specified
3. **MCP tools exist or are specced** — no undefined dependencies
4. **Revenue model is clear** — how the platform earns from this
5. **Agent benefit is stated** — how this makes the chain smarter

When graduated, an idea becomes a row in ToDo-JobBoard.md with:
- `task_id`: `IDEA-XXX` preserved
- `agent`: `level-N` based on complexity
- `gate`: `HOLD` until a GO signal from Level 5

---

*Ideas Database v0.1.0 | Last updated 2026-05-28*
