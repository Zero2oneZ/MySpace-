# THE RUST CHAIN

> What the **other half** (GentlyOS at `/data/Projects/gently/`) does, as understood by **this half** (MySpace++).
>
> Authoritative source: `/data/Projects/gently/CLAUDE.md` + `/data/Projects/gently/BB.md` + `/data/Projects/gently/REGISTRY.md`. This doc paraphrases for cross-side coordination.
>
> Companion: `NOTES-FOR-INFERANCE.md` (the comm channel) + `COMPLEX-DAG.svg` (the joint operational map).

---

## 1 · The one-sentence version

The Rust chain is a **content-addressed, deterministic stack-machine runtime** where every computation (UI screens, agent turns, ML inference, plan checkpoints, trade packets) is expressed as a `.bb` program; the program's execution emits a `crystal hash` that uniquely identifies the state; the chain of crystal hashes IS the system's memory. Self-referential because every output is itself a content-addressable key into the same store. Self-cleaning because tampering is detected by replaying the chain.

---

## 2 · The atoms

### `.bb` — the universal program format

A `.bb` is a stack machine with:

**2 value types**
- `StackVal::Num(f64)` — numbers, booleans, timestamps, costs
- `StackVal::Hash([u8;32])` — content addresses, identities, signatures

**7 frozen symbols** (the entire instruction set)
- `f` — false / no-op
- `~` — boolean NOT
- `d` — dup (push top again)
- `l` — load (read from variable)
- `s` — store (write to variable)
- `a` — apply (call a function reference)
- `m+/m-/m*/m/` — math ops

**Two wire formats**
- `gui.bb` — 136-byte fixed records (NODE/ROWX/ELEM/TRAN) for UI
- `program.bb` — text or binary stack-machine program + sidecar `seed.json`

**Determinism contract**
```
same .bb + same seed.json = same crystal hash, byte for byte, every time
```

That contract is the whole foundation. Everything downstream is consequences of holding it.

### Crystal hash — the identity

Execute a `.bb` program. Hash each emitted step. **XOR-chain** them in order. The final result is the program's `crystal hash`. Pin to IPFS → mint as a Sui NFT → the `.bb` IS the on-chain artifact.

Two key implications:
- **Self-reference**: a crystal hash can appear AS A value inside another `.bb` program. Programs can verify each other.
- **Self-cleaning**: replay any `.bb` with its seed; if the resulting crystal hash matches the claimed one, the program is genuine. If it doesn't, the state is corrupt OR the program was modified.

### Genesis anchor + mirror-pass

Two additional invariants make the chain hard to fake:

- **Genesis-anchored**: the runtime emits its own hash as `chain[0]`. Self-recognizes; can detect when an instance is impersonating it. Updates are null-addressed no-op extensions — never mutations of past entries.

- **Mirror-pass anti-particle**: every op has an antiparticle at the mirror position in the chain. `crystal = blake3(chain ⊕ anti_chain)`. To tamper with one entry you must also tamper with its mirror; you can't fake one without erasing both.

These together mean: forging a fake crystal hash requires forging *both* the forward chain and the inverse, which is exponentially harder.

### Open-window commit (SVG sessions)

While an agent is running, the session is an "open window" — SVG-active, no hashing. When the session is unplugged: deltas are clipped, the forward+mirror loop runs, and ONE chain extension is committed. Streaming privacy + k-anonymity per session. The 14 existing SVG waiting primitives in MySpace++'s wardrobe app **are** this same mechanism (from a planning note in our memory) — so the two halves share this concept.

---

## 3 · The Rust crates that make this real

(All in `/data/Projects/gently/crates/`. ~208 crates total; these are the chain-relevant ones.)

| Crate | What it does |
|---|---|
| **bb-emit** + **bb-emit-s2static** | Generate `.bb` UI from Rust struct attrs (`#[bb_node]` `#[bb_elem]` `#[bb_row]` `#[bb_tran]`) |
| **bb-loop** | Agent lifecycle. Every turn appends a fragment to `program.bb`. Emits cumulative crystal hashes. |
| **bb-runtime-adapter** | Adapter layer between `bb-loop` and the runtime's executor |
| **bb-cli** | CLI surface for `.bb` programs |
| **gently-crystal** | Crystal DAG: IPFS pin + Sui NFT per session |
| **gently-metabolism** | `OpKind` enum — the typed operation sequence that becomes a `.bb` step list |
| **gently-genesis** | Genesis anchor — chain[0] self-hash |
| **gently-content-hash** | Content addressing primitives |
| **gently-bb-struct** | Structural inversion — every program → canonical S-expression tree. Identifiers as searchable labels, not semantic identity. Rename-invariant dedup. |
| **gently-runtime** + **gently-spawn** + **gently-sim** | Runtime hosts (forward + mirror passes) |
| **telos-runtime** + **telos-dispatcher** + **telos-triggers** + **telos-skills** | Telos branch of the runtime — workflow orchestration |
| **telos-ml-tools** | The MCP-exposed inference tool. Routes opcodes to actual ML models. |
| **gently-inference** + **telos-inference** | Inference clients |
| **codie-engine** + **codie-v4-predict** + **gently-codie** | The compression + prediction layer. Like our TabPFN router but compiled. |

A `.bb` "agent turn" round-trip:

```
1. Agent (CC instance) wants to call model X with prompt P.
2. gently-metabolism encodes the call as OpKind::AgentPrompt
3. The OpKind is serialized as a .bb step (program.bb fragment)
4. bb-loop records the step; crystal_n = chain[0..n].xor()
5. telos-ml-tools MCP receives the .bb → looks up the model via codie-v4-predict
6. The model is invoked; output is captured
7. OpKind::VerifyHash runs against the response
8. Result is appended to program.bb as another .bb step
9. crystal_{n+1} = chain[0..n+1].xor()
10. The crystal hash is the verifiable receipt for the entire turn.
```

---

## 4 · Opcodes — the shared abstraction

Both halves understand **opcodes**. They are the bridge.

**On the MySpace++ side**: opcode = a row in `planning/hf_task_evolution.jsonl` (53 of them) — `Image Classification`, `Text-to-Speech`, `Image-Text-to-Video`, etc. Each row has typed inputs/outputs + dependencies + enables. This is the **catalog**.

**On the gently side**: opcode = `OpKind` enum variant in `gently-metabolism`. Each variant compiles to a `.bb` instruction sequence. This is the **executor**.

The bridge: when MySpace++ decides "this asset needs the `Image-Text-to-Video` opcode run on it", the work order is:
1. Look up the opcode in the shared catalog
2. Construct an `OpKind` sequence describing the call
3. Submit it to `telos-ml-tools` MCP (running on the droplet)
4. Get back a crystal hash receipt
5. Pull the result from IPFS using the crystal hash as the key

That's the entire interop story. Two halves, one shared opcode taxonomy, one `.bb` runtime as the deterministic spine, one Claude proxy for any frontier-model escalation.

---

## 5 · codie-v4-predict (the predictor)

The gently side's analogue to MySpace++'s `planning/TABPFN_ROUTER.md` design. Differences:

| Concern | MySpace++ TABPFN_ROUTER | gently codie-v4-predict |
|---|---|---|
| Language | Python | Rust |
| Backend | TabPFN (`pip install tabpfn`) OR k-NN fallback | compiled predictor (faster) |
| Training data | `cc.db tabpfn_examples` table | `crystal` chain (every committed turn is an example) |
| Output | top-K opcode + UI widgets + concrete model | OpKind enum + dispatch hint |
| Latency target | ≤150 ms | ≤10 ms (Rust + cache) |
| Determinism | "byte-identical given same examples" | "byte-identical given same chain head" |

They serve the same job. **The two should share training data via the shared opcode taxonomy** — every successful chain run on either side becomes an example for both. This requires us to define a JSONL export format both sides can read. **Q-MSPC-001** in the comm channel.

---

## 6 · Where the interop has to land

Three concrete bridges:

### A. The shared opcode taxonomy

`planning/hf_task_evolution.jsonl` is canonical. Both sides:
- Read it
- Refer to opcodes by their string `task` field (e.g. `"Image-Text-to-Video"`)
- Add new opcodes only by appending to this file (PRs from either half are fine; the dedup gate enforces no duplicates)

### B. The `.env` mirror

Already done. Both halves read the same 4 keys (`claude_guest`, `client_api`, `pintrest_api`, `SUI_WALLET`).

### C. The Claude proxy (and forward path)

- MySpace++ runs the Claude guest-pass proxy on port 8520 (`studio/proxy/claude_proxy.py`)
- gently's `telos-ml-tools` MCP calls Claude via this proxy when an opcode needs Claude
- Salted tokens (issued via `cc -keys-distribute`) gate access
- Both halves' usage shows up in `studio/auth/keys.sqlite`

### D. The crystal/piece interface

- MySpace++'s `passes.pieces_index` (`studio/cache/dag/pieces.sqlite`) records every computed piece keyed by content hash
- gently's `gently-crystal` records every chain extension keyed by crystal hash
- **Shared convention**: when MySpace++ runs an opcode whose execution should produce a chain extension, the piece's `content_hash` field should equal the crystal's blake3 hash. This makes the two side's content-address universes compatible.
- **Open**: who computes the canonical hash? Probably gently (it has the runtime). MySpace++ then mirrors the hash into pieces_index.

### E. WEAVE topology + crystal-anchored compute

- MySpace++'s WEAVE registers WebGPU workers (browser tabs)
- gently's `telos-runtime` registers Rust workers (native processes)
- **Bridge**: both should write to ONE shared topology view. Probably the WEAVE SQLite — gently writes Rust workers in as `kind='bot'` rows; MySpace++ writes browser-tab workers as `kind='browser-tab'`. Then routing decisions consult one source of truth.

---

## 7 · What I (MySpace++) can do today vs needs the other side

| Task | MySpace++ can | Needs gently |
|---|---|---|
| Run a Python pass on a .jpg | yes (passes/inference.py) | no |
| Route a pass to a browser tab | yes (weave/routing.py) | no |
| Author a workflow template via Claude | yes (cc -authorize-templates) | no |
| Get a crystal hash for a chain run | no | YES (gently-crystal) |
| Verify a chain hasn't been tampered with | no | YES (mirror-pass) |
| Express an opcode call as `.bb` | no | YES (gently-metabolism OpKind) |
| Call telos-ml-tools MCP from cc | no — bridge not built | YES (gently exposes MCP) |
| Pull a result from IPFS by hash | no | YES (gently-ipfs) |
| Mint a Sui NFT for a session | no | YES (gently-crystal + gently-sui) |
| Run codie-v4-predict for next-opcode | no | YES (gently) |
| Run TabPFN for next-opcode | YES (planning/TABPFN_ROUTER.md — not yet built) | no |

The complementarity is clean. The gap closes when:
1. MySpace++ exposes its routing decisions as an MCP tool so gently can read them
2. gently exposes `telos-ml-tools` reachable from cc dispatch (probably `cc -mcp-call telos-ml-tools ...`)
3. The shared opcode taxonomy is the contract

That's what `NOTES-FOR-INFERANCE.md` is going to coordinate.

---

## 8 · Open questions toward the other side

Listed individually in `NOTES-FOR-INFERANCE.md` Q&A section. Summary:
- How do you want to read MySpace++'s `pieces_index` from gently?
- Should WEAVE topology be a single SQLite, or two with a merge?
- Who owns the `tabpfn_examples` / training-data export format?
- Is `telos-ml-tools` already reachable from outside the gently process tree, or is wrapping needed?
- Where does the crystal hash for a MySpace++-side computation get registered?

---

## 9 · What I (this doc) will keep updated

This file is **MySpace++'s best understanding of the Rust chain**. It will drift from gently's truth — when it does, that's the gently half's signal to update us via `NOTES-FOR-INFERANCE.md` (or to ask us to update this file).

Source of truth for the Rust chain: `/data/Projects/gently/CLAUDE.md` + `BB.md`. This doc paraphrases.
