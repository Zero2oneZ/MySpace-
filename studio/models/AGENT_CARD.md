# Agent Card: Unified Model Installer (`core/lib/model_installer.py`)

> **Scope:** `studio/models/` — canonical model registry for MySpace++ inference substrate.  
> **Last updated:** 2026-05-28  
> **Determinism:** same query + same category/subtype → same canonical path, every time.

---

## 1. What This Does (One Paragraph)

A single unified interface to **search**, **download**, **install**, and **register** models from HuggingFace Hub and Ollama into the canonical `studio/models/` tree. Every model gets a deterministic file path, a VM-CONSOLIDATION config JSON, and an entry in `registry.json`. The rest of the system (token_router, chat.py, model_registry.py, Godot bridge) reads from this registry. No manual file management. No duplicate weights. One source of truth.

---

## 2. Directory Layout (Canonical)

```
studio/models/
├── README.md                 # project-level docs
├── registry.json             # SINGLE SOURCE OF TRUTH (auto-generated)
├── tools/                    # inference tooling
├── loras/                    # LoRA adapters
├── huggingface/              # HF Hub downloads
│   ├── text_generation/{code,chat,reasoning,...}
│   ├── vision/{depth_estimation,pose_detection,...}
│   ├── audio/{text_to_speech,speech_to_text,...}
│   ├── multimodal/{vision_language,audio_language,...}
│   └── embeddings/{text,image,audio,multimodal}
├── ollama/                   # Ollama pulls
│   ├── text_generation/{code,chat,reasoning}
│   ├── vision/
│   └── embeddings/text
└── cloud/                    # frontier APIs (config only, no weights)
    ├── anthropic/{reasoning,code,chat}
    ├── grok/{reasoning,chat}
    └── openai/{reasoning,code,chat,embeddings}
```

### Naming Convention (VM-CONSOLIDATION §9)

```
vm_mspc_001.{brand}.{category}.{subtype}.{model_name}.{state}.{version}.json
```

Examples:
- `vm_mspc_001.huggingface.vision.depth_estimation.depth_pro.active.v0.json`
- `vm_mspc_001.ollama.text_generation.code.qwen2_5_coder_1_5b.active.v0.json`
- `vm_mspc_001.cloud.anthropic.reasoning.claude_opus_4_7.active.v0.json`

**State transitions by `mv`:** `active` → `archived` → `deleted`. Never mutate. Always move.

---

## 3. Category Taxonomy (43 Subtypes)

| Category | Subtypes |
|---|---|
| `text_generation` | `code`, `chat`, `reasoning`, `instruction`, `creative_writing`, `summarization`, `translation`, `question_answering`, `text_classification` |
| `vision` | `depth_estimation`, `pose_detection`, `image_to_3d`, `image_classification`, `object_detection`, `segmentation`, `optical_character_recognition`, `image_generation` |
| `audio` | `text_to_speech`, `speech_to_text`, `speech_enhancement`, `music_generation`, `voice_conversion`, `audio_classification` |
| `multimodal` | `vision_language`, `audio_language`, `video_language`, `image_to_text`, `text_to_image`, `text_to_video`, `text_to_3d` |
| `embeddings` | `text`, `image`, `audio`, `multimodal` |
| `specialized` | `legal`, `medical`, `financial`, `scientific`, `educational`, `gaming` |
| `tools` | `conversion`, `quantization`, `evaluation` |

---

## 4. Commands (Exact Usage)

### 4.1 Search

Search across HuggingFace Hub + Ollama library simultaneously.

```bash
cc model-search "depth estimation"
cc model-search "qwen code"
cc model-search "whisper" --source hf       # HuggingFace only
cc model-search "llama" --source ollama     # Ollama only
```

Output columns: `SOURCE`, `ID`, `NAME`, `DOWNLOADS`.

---

### 4.2 Install HuggingFace Model

Downloads weights via `huggingface-cli` or `huggingface_hub` Python library.

```bash
cc model-install \
  --hf "apple/DepthPro" \
  --category vision \
  --subtype depth_estimation \
  --display-name "Depth Pro" \
  --tags "spatial,vision,heavy"
```

What happens:
1. Runs `huggingface-cli download apple/DepthPro --local-dir studio/models/huggingface/vision/depth_estimation/apple--DepthPro`
2. Creates config JSON: `vm_mspc_001.huggingface.vision.depth_estimation.depth_pro.active.v0.json`
3. Appends entry to `registry.json`
4. Computes SHA-256 crystal hash of the config

**Prerequisites:**
```bash
pip install huggingface-hub      # if not using huggingface-cli
huggingface-cli login            # for gated/private models
```

---

### 4.3 Install Ollama Model

Pulls via `ollama` CLI and registers.

```bash
cc model-install \
  --ollama "qwen2.5-coder:1.5b" \
  --category text_generation \
  --subtype code \
  --display-name "Qwen2.5 Coder 1.5B" \
  --tags "tiny,fast,deterministic"
```

What happens:
1. Runs `ollama pull qwen2.5-coder:1.5b`
2. Weights live at `~/.ollama/models/` (managed by Ollama)
3. Creates config JSON: `vm_mspc_001.ollama.text_generation.code.qwen2_5_coder_1_5b.active.v0.json`
4. Appends entry to `registry.json`
5. Captures `ollama show --json` metadata into config

**Prerequisites:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve                     # if not already running
```

---

### 4.4 Install Cloud Model (Manual Registration)

Cloud models have no weights. You register them by creating the config JSON directly.

```bash
# Create the config file
$EDITOR studio/models/cloud/anthropic/reasoning/vm_mspc_001.cloud.anthropic.reasoning.claude_opus_4_7.active.v0.json

# Then sync registry
cc model-sync
```

Config template:
```json
{
  "_schema": "model_config_v1",
  "asset_id": "vm_mspc_001.cloud.anthropic.reasoning.claude_opus_4_7.active.v0.json",
  "crystal": "sha256:...",
  "vm_id": "vm_mspc_001",
  "brand": "cloud",
  "provider": "anthropic",
  "category": "reasoning",
  "subtype": "epic",
  "name": "claude-opus-4-7",
  "display_name": "Claude Opus 4.7",
  "context_window": 200000,
  "quantization": "cloud",
  "vram_gb": 0,
  "state": "active",
  "version": "v0",
  "routing": {
    "tier": "epic",
    "scope": "epic",
    "tags": ["epic", "cloud", "frontier", "synthesis"]
  },
  "endpoints": {
    "rest": "https://api.anthropic.com/v1/messages"
  },
  "capabilities": {
    "vision": true,
    "code": true,
    "tool_use": true,
    "streaming": true
  }
}
```

---

### 4.5 List Installed Models

```bash
cc model-list                      # all active models
cc model-list --brand ollama       # filter by brand
cc model-list --category vision    # filter by category
cc model-list --subtype code       # filter by subtype
```

Output columns: `NAME`, `BRAND`, `CATEGORY`, `SUBTYPE`, `STATE`.

---

### 4.6 Show Taxonomy

```bash
cc model-taxonomy
```

Prints all 7 categories + 43 subtypes. Use this when you don't know which `--subtype` to pick.

---

### 4.7 Sync Registry

Rebuild `registry.json` by scanning all config files on disk.

```bash
cc model-sync
```

Run this after:
- Manual config edits
n- Moving files between `active`/`archived`/`deleted` states
- Git pulls that added new model configs
- Any operation that touched `studio/models/` outside the installer

---

## 5. Python API

Import and use programmatically from other scripts:

```python
from model_installer import ModelInstaller, ModelCandidate

installer = ModelInstaller()

# Search
results = installer.search("depth estimation", source="both", limit=10)
for r in results:
    print(r.source, r.id)

# Install HF
result = installer.install_hf(
    repo_id="apple/DepthPro",
    category="vision",
    subtype="depth_estimation",
    display_name="Depth Pro",
    tags=["spatial", "vision", "heavy"]
)
print(result.asset_id, result.crystal)

# Install Ollama
result = installer.install_ollama(
    model_name="qwen2.5-coder:1.5b",
    category="text_generation",
    subtype="code"
)

# List
models = installer.list_installed(brand="ollama", category="text_generation")
for m in models:
    print(m["name"], m["tier"])

# Sync
stats = installer.sync_registry()
print(f"Rebuilt: {stats['models']} models")
```

---

## 6. Integration Points

### Token Router (`core/lib/token_router.py`)
- Reads default tier models from `registry.json` instead of hardcoded env vars
- `ModelRouter.route(prompt)` → resolves `tier` → looks up `model_id` from registry
- If `ollama` model with `context_window < token_count`, falls through to cloud

### Model Registry (`core/lib/model_registry.py`)
- Single Python API over `registry.json`
- Methods: `by_name()`, `by_tier()`, `by_brand()`, `by_category()`, `by_tag()`, `resolve_for_tokens()`, `vram_budget()`
- Used by chat.py to show which model was selected

### Chat Gateway (`core/lib/chat.py`)
- After every `cc chat` call, logs inference with `model` and `tier` to crystal chain
- Downward dispatch slices reference exact model IDs from registry

### Godot Bridge (`studio/godot/project/src/cc_bridge.gd`)
- Receives `route.model` from registry
- Can trigger `build_gdext` action if model is native C++

### Inference Logger (`core/lib/inference_logger.py`)
- Every model call writes: `model`, `tier`, `tokens_in`, `tokens_out`
- Chain of chains is searchable by model name: `cc inference-search "claude-opus"`

---

## 7. Determinism Rules

1. **Same query + same category/subtype → same canonical path.** The installer computes the `asset_id` deterministically from `repo_id` or `model_name`.
2. **Registry is append-only.** Never delete rows; change `state` to `archived`.
3. **Config JSONs are the truth.** If registry.json disagrees with disk, run `cc model-sync`.
4. **Crystal hashes cover config + metadata, not weights.** Weight hashes are handled by `huggingface-cli` or `ollama` natively.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `huggingface-cli not found` | `pip install huggingface-hub` then `huggingface-cli login` |
| `ollama not found` | `curl -fsSL https://ollama.com/install.sh \| sh` |
| `Unknown category` | Run `cc model-taxonomy` to see valid categories |
| `Unknown subtype` | Check CATEGORY_TAXONOMY in `model_installer.py` or run `cc model-taxonomy` |
| `registry.json out of sync` | Run `cc model-sync` |
| `Model not showing in tier routing` | Verify `tags` include `"tiny"`/`"medium"`/`"large"`/`"epic"` |
| `HF download hangs` | Check `HF_HOME` env var; default is `~/.cache/huggingface` |
| `Ollama pull fails` | Ensure `ollama serve` is running on localhost:11434 |

---

## 9. Quick Reference (Cheatsheet)

```bash
# Search
cc model-search "depth estimation"
cc model-search "qwen" --source ollama

# Install
cc model-install --hf "apple/DepthPro" --category vision --subtype depth_estimation
cc model-install --ollama "qwen2.5-coder:1.5b" --category text_generation --subtype code

# List
cc model-list
cc model-list --brand ollama --category text_generation

# Taxonomy
cc model-taxonomy

# Sync
cc model-sync

# Verify chain integrity
cc inference-verify

# Search inference logs by model
cc inference-search "claude-opus"
```

---

**Card ID:** `agent-card:model-installer-v1`  
**Deterministic:** yes (same inputs → same paths, same registry entries)  
**Required context:** `studio/models/README.md`, `VM-CONSOLIDATION.md §9`
