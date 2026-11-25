#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        model_installer                                                =
# role:        INSTALLER · MODEL_LIFECYCLE                                    =
# tier:        L0                                                             =
# substrate:   studio/models tree (canonical model corpus)                    =
# engine:      subprocess huggingface-cli + ollama, with Python fallback     =
# storage:     studio/models/{brand}/{category}/{subtype}/                   =
#              studio/models/registry.json                                    =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.model_installer.active.json      =
# in-tree:     studio/models/AGENT_CARD.md (kimi's original markdown doc)    =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - core/cc.sh::cmd_model_*  (search / install / list / taxonomy / sync)   =
#   - CLI: python3 model_installer.py <subcmd>                                =
# outbound:                                                                   =
#   - subprocess huggingface-cli, ollama                                      =
#   - Python: huggingface_hub, ollama (fallback)                              =
# substrate touch:                                                            =
#   - reads:  studio/models/registry.json (for list / sync)                   =
#   - writes: studio/models/{brand}/{category}/{subtype}/<files> +           =
#             per-model JSON + registry.json                                  =
# consumed by:                                                                =
#   - model_registry.py  (lookup over registry.json)                          =
#   - token_router.py    (tier resolution via ModelRegistry)                  =
#   - forward_projector  (CC_TINY_MODEL default from installed Ollama)        =
# ============================================================================
"""model_installer.py — unified HuggingFace + Ollama search, download, and install.

Installs models into the canonical studio/models/ tree using VM-CONSOLIDATION naming:
  studio/models/{brand}/{category}/{subtype}/

Supports:
  - huggingface-cli  (pip install huggingface-hub)
  - ollama CLI       (curl -fsSL https://ollama.com/install.sh | sh)
  - Python fallback: huggingface_hub, ollama libraries

Every install creates:
  1. Model weights in the correct brand/category/subtype/ directory
  2. Canonical config JSON: vm_mspc_001.{brand}.{category}.{subtype}.{name}.{state}.{version}.json
  3. Registry entry in studio/models/registry.json

Usage:
    python3 model_installer.py search --hf --query "depth estimation"
    python3 model_installer.py search --ollama --query "qwen"
    python3 model_installer.py install --hf "apple/DepthPro" --category vision --subtype depth_estimation
    python3 model_installer.py install --ollama "qwen2.5-coder:1.5b" --category text_generation --subtype code
    python3 model_installer.py list --brand ollama --category text_generation
    python3 model_installer.py sync-registry
"""
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any

# Paths
STUDIO_ROOT = Path(__file__).parent.parent.parent / "studio"
MODELS_ROOT = STUDIO_ROOT / "models"
REGISTRY_PATH = MODELS_ROOT / "registry.json"
CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))

# Comprehensive category taxonomy
CATEGORY_TAXONOMY: Dict[str, List[str]] = {
    "text_generation": [
        "code", "chat", "reasoning", "instruction",
        "creative_writing", "summarization", "translation",
        "question_answering", "text_classification"
    ],
    "vision": [
        "depth_estimation", "pose_detection", "image_to_3d",
        "image_classification", "object_detection", "segmentation",
        "optical_character_recognition", "image_generation"
    ],
    "audio": [
        "text_to_speech", "speech_to_text", "speech_enhancement",
        "music_generation", "voice_conversion", "audio_classification"
    ],
    "multimodal": [
        "vision_language", "audio_language", "video_language",
        "image_to_text", "text_to_image", "text_to_video", "text_to_3d"
    ],
    "embeddings": [
        "text", "image", "audio", "multimodal"
    ],
    "specialized": [
        "legal", "medical", "financial", "scientific",
        "educational", "gaming"
    ],
    "tools": [
        "conversion", "quantization", "evaluation"
    ]
}

ALL_SUBTYPES: List[str] = [s for subs in CATEGORY_TAXONOMY.values() for s in subs]


@dataclass
class ModelCandidate:
    """A model found by search, before installation."""
    source: str           # "huggingface" | "ollama"
    id: str               # repo_id or ollama name
    name: str             # display name
    category: str = ""
    subtype: str = ""
    description: str = ""
    tags: List[str] = None
    downloads: int = 0
    likes: int = 0
    last_modified: str = ""

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class InstallResult:
    success: bool
    asset_id: str = ""
    config_path: str = ""
    weights_path: str = ""
    message: str = ""
    crystal: str = ""


class ModelInstaller:
    """Unified HF + Ollama installer."""

    def __init__(self, models_root: Optional[Path] = None):
        self.models_root = models_root or MODELS_ROOT
        self.registry_path = REGISTRY_PATH
        self._ensure_dirs()
        self._registry = self._load_registry()

    def _ensure_dirs(self) -> None:
        """Create all category/subtype directories."""
        for brand in ("huggingface", "ollama", "cloud"):
            for category, subtypes in CATEGORY_TAXONOMY.items():
                for subtype in subtypes:
                    (self.models_root / brand / category / subtype).mkdir(
                        parents=True, exist_ok=True
                    )
        (self.models_root / "tools").mkdir(exist_ok=True)
        (self.models_root / "loras").mkdir(exist_ok=True)

    def _load_registry(self) -> Dict:
        if self.registry_path.exists():
            try:
                return json.loads(self.registry_path.read_text())
            except Exception:
                pass
        return {
            "_schema": "model_registry_v1",
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "models": [],
            "tools": [],
            "loras": []
        }

    def _save_registry(self) -> None:
        self.registry_path.write_text(
            json.dumps(self._registry, indent=2, sort_keys=False),
            encoding="utf-8"
        )

    def _has_hf_cli(self) -> bool:
        return subprocess.run(
            ["which", "huggingface-cli"], capture_output=True
        ).returncode == 0

    def _has_ollama_cli(self) -> bool:
        return subprocess.run(
            ["which", "ollama"], capture_output=True
        ).returncode == 0

    def _vm_id(self) -> str:
        return "vm_mspc_001"

    def _asset_id(self, brand: str, category: str, subtype: str, name: str, state: str = "active", version: str = "v0") -> str:
        """Canonical asset ID per VM-CONSOLIDATION."""
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", name).lower()
        return f"{self._vm_id()}.{brand}.{category}.{subtype}.{safe_name}.{state}.{version}.json"

    def _crystal_hash(self, data: str) -> str:
        import hashlib
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search_hf(self, query: str, limit: int = 20) -> List[ModelCandidate]:
        """Search HuggingFace Hub via CLI or API."""
        candidates = []

        # Try huggingface_hub Python library
        try:
            from huggingface_hub import HfApi
            api = HfApi()
            models = api.list_models(
                search=query,
                sort="downloads",
                direction=-1,
                limit=limit
            )
            for m in models:
                candidates.append(ModelCandidate(
                    source="huggingface",
                    id=m.modelId,
                    name=m.modelId.split("/")[-1],
                    description=getattr(m, "cardData", {}).get("description", "") if hasattr(m, "cardData") else "",
                    tags=list(getattr(m, "tags", [])),
                    downloads=getattr(m, "downloads", 0),
                    likes=getattr(m, "likes", 0),
                    last_modified=getattr(m, "lastModified", "")
                ))
            return candidates
        except ImportError:
            pass

        # Fallback: huggingface-cli
        if self._has_hf_cli():
            try:
                result = subprocess.run(
                    ["huggingface-cli", "search", query, "--limit", str(limit)],
                    capture_output=True, text=True, timeout=30
                )
                # Parse tabular output
                for line in result.stdout.splitlines()[1:]:  # skip header
                    parts = line.split()
                    if len(parts) >= 2:
                        candidates.append(ModelCandidate(
                            source="huggingface",
                            id=parts[0],
                            name=parts[0].split("/")[-1]
                        ))
            except Exception:
                pass

        return candidates

    def search_ollama(self, query: str, limit: int = 20) -> List[ModelCandidate]:
        """Search Ollama library via CLI or API."""
        candidates = []

        # Try ollama Python library
        try:
            import ollama
            models = ollama.list()
            for m in models.get("models", []):
                name = m.get("name", "")
                if query.lower() in name.lower():
                    candidates.append(ModelCandidate(
                        source="ollama",
                        id=name,
                        name=name,
                        description=f"Size: {m.get('size', 'unknown')}",
                        tags=[m.get("details", {}).get("family", "")]
                    ))
                if len(candidates) >= limit:
                    break
            return candidates
        except ImportError:
            pass

        # Fallback: ollama CLI
        if self._has_ollama_cli():
            try:
                result = subprocess.run(
                    ["ollama", "list"],
                    capture_output=True, text=True, timeout=30
                )
                for line in result.stdout.splitlines()[1:]:
                    parts = line.split()
                    if parts and query.lower() in parts[0].lower():
                        candidates.append(ModelCandidate(
                            source="ollama",
                            id=parts[0],
                            name=parts[0]
                        ))
                    if len(candidates) >= limit:
                        break
            except Exception:
                pass

        return candidates

    def search(self, query: str, source: str = "both", limit: int = 20) -> List[ModelCandidate]:
        """Unified search across both sources."""
        results = []
        if source in ("both", "hf", "huggingface"):
            results.extend(self.search_hf(query, limit))
        if source in ("both", "ollama"):
            results.extend(self.search_ollama(query, limit))
        # Sort by relevance (downloads for HF, name match for Ollama)
        results.sort(key=lambda x: x.downloads, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------
    def install_hf(self, repo_id: str, category: str, subtype: str, **kwargs) -> InstallResult:
        """Download a HuggingFace model and install into canonical path."""
        if category not in CATEGORY_TAXONOMY:
            return InstallResult(False, message=f"Unknown category: {category}")
        if subtype not in CATEGORY_TAXONOMY.get(category, []):
            return InstallResult(False, message=f"Unknown subtype '{subtype}' for category '{category}'")

        install_dir = self.models_root / "huggingface" / category / subtype
        install_dir.mkdir(parents=True, exist_ok=True)

        # Download via huggingface-cli or hub
        local_path = install_dir / repo_id.replace("/", "--")

        if self._has_hf_cli():
            try:
                subprocess.run(
                    ["huggingface-cli", "download", repo_id, "--local-dir", str(local_path)],
                    check=True, timeout=600
                )
            except subprocess.CalledProcessError as e:
                return InstallResult(False, message=f"HF download failed: {e}")
        else:
            try:
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id, local_dir=str(local_path))
            except ImportError:
                return InstallResult(
                    False,
                    message="huggingface-cli or huggingface_hub required. Install: pip install huggingface-hub"
                )

        # Create canonical config
        name = repo_id.split("/")[-1]
        asset_id = self._asset_id("huggingface", category, subtype, name)
        config_path = install_dir / asset_id

        config = {
            "_schema": "model_config_v1",
            "asset_id": asset_id,
            "crystal": self._crystal_hash(json.dumps(kwargs, sort_keys=True)),
            "vm_id": self._vm_id(),
            "brand": "huggingface",
            "provider": "huggingface_hub",
            "category": category,
            "subtype": subtype,
            "name": repo_id,
            "display_name": kwargs.get("display_name", name),
            "local_path": str(local_path.relative_to(self.models_root)),
            "state": "active",
            "version": "v0",
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tags": kwargs.get("tags", ["huggingface", category, subtype]),
        }
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        # Update registry
        self._registry["models"].append(config)
        self._save_registry()

        return InstallResult(
            success=True,
            asset_id=asset_id,
            config_path=str(config_path),
            weights_path=str(local_path),
            message=f"Installed {repo_id} to {install_dir}",
            crystal=config["crystal"]
        )

    def install_ollama(self, model_name: str, category: str, subtype: str, **kwargs) -> InstallResult:
        """Pull an Ollama model and register in canonical path."""
        if category not in CATEGORY_TAXONOMY:
            return InstallResult(False, message=f"Unknown category: {category}")
        if subtype not in CATEGORY_TAXONOMY.get(category, []):
            return InstallResult(False, message=f"Unknown subtype '{subtype}' for category '{category}'")

        install_dir = self.models_root / "ollama" / category / subtype
        install_dir.mkdir(parents=True, exist_ok=True)

        # Pull via ollama CLI
        if self._has_ollama_cli():
            try:
                subprocess.run(
                    ["ollama", "pull", model_name],
                    check=True, timeout=600
                )
            except subprocess.CalledProcessError as e:
                return InstallResult(False, message=f"Ollama pull failed: {e}")
        else:
            return InstallResult(
                False,
                message="ollama CLI required. Install: curl -fsSL https://ollama.com/install.sh | sh"
            )

        # Create canonical config
        safe_name = model_name.replace(":", "_").replace("/", "_")
        asset_id = self._asset_id("ollama", category, subtype, safe_name)
        config_path = install_dir / asset_id

        # Get model info
        model_info = {}
        try:
            result = subprocess.run(
                ["ollama", "show", model_name, "--json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                model_info = json.loads(result.stdout)
        except Exception:
            pass

        config = {
            "_schema": "model_config_v1",
            "asset_id": asset_id,
            "crystal": self._crystal_hash(json.dumps(model_info, sort_keys=True)),
            "vm_id": self._vm_id(),
            "brand": "ollama",
            "provider": "ollama",
            "category": category,
            "subtype": subtype,
            "name": model_name,
            "display_name": kwargs.get("display_name", model_name),
            "local_path": f"~/.ollama/models/{model_name}",
            "state": "active",
            "version": "v0",
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tags": kwargs.get("tags", ["ollama", category, subtype, "local"]),
            "ollama_info": model_info,
        }
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        # Update registry
        self._registry["models"].append(config)
        self._save_registry()

        return InstallResult(
            success=True,
            asset_id=asset_id,
            config_path=str(config_path),
            weights_path=f"~/.ollama/models/{model_name}",
            message=f"Pulled {model_name} via Ollama",
            crystal=config["crystal"]
        )

    def sync_registry(self) -> Dict:
        """Scan all config files in studio/models/ and rebuild registry.json."""
        models = []
        tools = []
        loras = []

        for brand in ("huggingface", "ollama", "cloud"):
            for category, subtypes in CATEGORY_TAXONOMY.items():
                for subtype in subtypes:
                    dir_path = self.models_root / brand / category / subtype
                    if not dir_path.exists():
                        continue
                    for config_file in dir_path.glob("*.json"):
                        try:
                            data = json.loads(config_file.read_text())
                            if data.get("_schema") == "model_config_v1":
                                models.append(data)
                        except Exception:
                            continue

        # Scan tools and loras
        for subdir, target_list in (("tools", tools), ("loras", loras)):
            dir_path = self.models_root / subdir
            if dir_path.exists():
                for config_file in dir_path.glob("*.json"):
                    try:
                        data = json.loads(config_file.read_text())
                        target_list.append(data)
                    except Exception:
                        continue

        self._registry = {
            "_schema": "model_registry_v1",
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "models": models,
            "tools": tools,
            "loras": loras,
        }
        self._save_registry()
        return {"models": len(models), "tools": len(tools), "loras": len(loras)}

    def list_installed(self, brand: Optional[str] = None, category: Optional[str] = None, subtype: Optional[str] = None) -> List[Dict]:
        """List installed models from registry."""
        models = self._registry.get("models", [])
        if brand:
            models = [m for m in models if m.get("brand") == brand]
        if category:
            models = [m for m in models if m.get("category") == category]
        if subtype:
            models = [m for m in models if m.get("subtype") == subtype]
        return models


def main():
    import argparse
    ap = argparse.ArgumentParser(description="model_installer — unified HF + Ollama manager")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # Search
    p_search = sub.add_parser("search", help="search models")
    p_search.add_argument("query", help="search query")
    p_search.add_argument("--source", choices=["both", "hf", "ollama"], default="both")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--json", action="store_true")

    # Install
    p_install = sub.add_parser("install", help="install a model")
    p_install.add_argument("--hf", help="HuggingFace repo_id to install")
    p_install.add_argument("--ollama", help="Ollama model name to pull")
    p_install.add_argument("--category", required=True, choices=list(CATEGORY_TAXONOMY.keys()))
    p_install.add_argument("--subtype", required=True)
    p_install.add_argument("--display-name", default="")
    p_install.add_argument("--tags", default="")

    # List
    p_list = sub.add_parser("list", help="list installed models")
    p_list.add_argument("--brand")
    p_list.add_argument("--category")
    p_list.add_argument("--subtype")
    p_list.add_argument("--json", action="store_true")

    # Taxonomy
    p_tax = sub.add_parser("taxonomy", help="show category taxonomy")

    # Sync
    p_sync = sub.add_parser("sync-registry", help="rebuild registry from disk")

    args = ap.parse_args()
    installer = ModelInstaller()

    if args.cmd == "search":
        results = installer.search(args.query, args.source, args.limit)
        if args.json:
            print(json.dumps([asdict(r) for r in results], indent=2))
        else:
            print(f"{'SOURCE':12} {'ID':40} {'NAME':30} {'DOWNLOADS':10}")
            print("-" * 100)
            for r in results:
                print(f"{r.source:12} {r.id:40} {r.name:30} {r.downloads:10}")

    elif args.cmd == "install":
        kwargs = {"display_name": args.display_name}
        if args.tags:
            kwargs["tags"] = args.tags.split(",")

        if args.hf:
            result = installer.install_hf(args.hf, args.category, args.subtype, **kwargs)
        elif args.ollama:
            result = installer.install_ollama(args.ollama, args.category, args.subtype, **kwargs)
        else:
            print("Error: specify --hf or --ollama", file=sys.stderr)
            sys.exit(1)

        print(json.dumps(asdict(result), indent=2))

    elif args.cmd == "list":
        models = installer.list_installed(args.brand, args.category, args.subtype)
        if args.json:
            print(json.dumps(models, indent=2))
        else:
            print(f"{'NAME':35} {'BRAND':12} {'CATEGORY':16} {'SUBTYPE':20} {'STATE':8}")
            print("-" * 95)
            for m in models:
                print(f"{m.get('name',''):35} {m.get('brand',''):12} {m.get('category',''):16} {m.get('subtype',''):20} {m.get('state',''):8}")

    elif args.cmd == "taxonomy":
        for category, subtypes in CATEGORY_TAXONOMY.items():
            print(f"\n{category}")
            for s in subtypes:
                print(f"  - {s}")
        print(f"\nTotal categories: {len(CATEGORY_TAXONOMY)}")
        print(f"Total subtypes: {len(ALL_SUBTYPES)}")

    elif args.cmd == "sync-registry":
        stats = installer.sync_registry()
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
