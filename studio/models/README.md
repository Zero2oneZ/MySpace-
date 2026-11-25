# studio/models/ — Model Registry Root

> **Canonical model storage for MySpace++ inference substrate.**
> Every model, tool, LoRA, and adapter lives here with deterministic addressing.

## Directory Layout

```
studio/models/
├── README.md                 # this file
├── registry.json             # canonical registry of ALL models (single source of truth)
├── tools/                    # inference tooling (scripts, converters, quantizers)
│   └── .gitkeep
├── loras/                    # LoRA adapters (per-model subdirs)
│   └── .gitkeep
├── huggingface/              # HuggingFace models (downloaded weights)
│   ├── text_generation/      # category
│   │   ├── code/             # subtype
│   │   ├── chat/
│   │   └── reasoning/
│   ├── vision/
│   │   ├── depth_estimation/
│   │   ├── pose_detection/
│   │   └── image_to_3d/
│   ├── audio/
│   │   ├── text_to_speech/
│   │   └── speech_to_text/
│   └── multimodal/
│       └── vision_language/
├── ollama/                   # Ollama-managed local models
│   ├── text_generation/
│   │   ├── code/
│   │   ├── chat/
│   │   └── reasoning/
│   ├── vision/
│   │   └── (ollama vision support expanding)
│   └── embeddings/
│       └── text/
└── cloud/                    # Frontier API models (no weights stored; config only)
    ├── anthropic/            # Claude family
    │   ├── reasoning/
    │   ├── code/
    │   └── chat/
    ├── grok/                 # xAI Grok family
    │   ├── reasoning/
    │   └── chat/
    └── openai/               # GPT family
        ├── reasoning/
        ├── code/
        ├── chat/
        └── embeddings/
```

## Naming Convention

Every model file uses the canonical VM-CONSOLIDATION pattern:

```
{symbol}{array}.{brand}.{category}.{subtype}.{model_name}.{state}.{version}.json
```

Examples:
- `vm_mspc_001.huggingface.text_generation.code.qwen3-coder-next.latest.v0.json`
- `vm_mspc_001.ollama.text_generation.code.qwen2.5-coder.1_5b.v0.json`
- `vm_mspc_001.cloud.anthropic.reasoning.claude-opus-4-7.active.v0.json`
- `vm_mspc_001.cloud.openai.code.gpt-4o.active.v0.json`

## registry.json Schema

```json
{
  "_schema": "model_registry_v1",
  "last_updated": "2026-05-28T00:00:00Z",
  "models": [
    {
      "asset_id": "vm_mspc_001.ollama.text_generation.code.qwen2.5-coder.1_5b.v0.json",
      "brand": "ollama",
      "category": "text_generation",
      "subtype": "code",
      "name": "qwen2.5-coder:1.5b",
      "display_name": "Qwen2.5 Coder 1.5B",
      "context_window": 32768,
      "quantization": "Q4_K_M",
      "vram_gb": 1.2,
      "state": "active",
      "crystal": "sha256:...",
      "path": "studio/models/ollama/text_generation/code/"
    }
  ]
}
```

## Rules

1. **One registry to rule them all.** `registry.json` is the ONLY canonical list.
2. **No weights in git.** All `.gguf`, `.safetensors`, `.bin` files are ignored.
3. **Config IS tracked.** Every model has a `.json` config file with metadata, hashes, and routing rules.
4. **State transitions by rename.** `active` → `archived` → `deleted` via `mv`.
5. **Deterministic routing.** The token_router reads this registry to resolve model IDs.
