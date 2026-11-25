#!/usr/bin/env bash
# ============================================================================
# model_index.sh — model registry indexer.
#
# Walks /home/tom/models (default) + any other model roots given as args.
# Classifies each model file by:
#   * extension (.safetensors / .ckpt / .pt / .pth / .gguf / .bin / .onnx / .lora)
#   * directory hint (lora / vae / controlnet / checkpoint / embedding / upscaler / clip)
#   * size bucket (embedding / lora / small_model / base / large / huge)
#
# Emits a deterministic JSONL chain (ParserCursor-compatible). Pipe to
# ~/.cc/model_index.jsonl. Consumed by token_router, workflow cards, and
# SpriteForge's ComfyUI bridge.
#
# Usage:
#   model_index.sh [root1] [root2] ...
#   default root: /home/tom/models
# ============================================================================

set -euo pipefail

ROOTS=("$@")
[ ${#ROOTS[@]} -eq 0 ] && ROOTS=(/home/tom/models)

jline() {
  python3 -c '
import json, sys
d = {}
for arg in sys.argv[1:]:
    k, _, v = arg.partition("=")
    try:
        d[k] = json.loads(v) if v and v[0] in "{[\"0123456789tfn-" else v
    except json.JSONDecodeError:
        d[k] = v
sys.stdout.write(json.dumps(d, ensure_ascii=True, sort_keys=True, separators=(",",":")))
sys.stdout.write("\n")
' "$@"
}

# Classify a single model file based on path + size
classify() {
  local rel="$1"
  local fname="$2"
  local size="$3"
  local lc_rel; lc_rel=$(echo "$rel" | tr '[:upper:]' '[:lower:]')
  local lc_fname; lc_fname=$(echo "$fname" | tr '[:upper:]' '[:lower:]')

  case "$lc_rel" in
    *lora*)        echo lora;       return ;;
    *controlnet*)  echo controlnet; return ;;
    *control_net*) echo controlnet; return ;;
    *upscaler*|*esrgan*|*upscale*) echo upscaler; return ;;
    *embedding*|*textual_inversion*) echo embedding; return ;;
    *clip*|*text_encoder*) echo clip; return ;;
    *vae*) echo vae; return ;;
    *tts*|*voice*) echo tts; return ;;
    *whisper*|*asr*) echo asr; return ;;
  esac
  case "$lc_fname" in
    *lora*) echo lora; return ;;
    *control*) echo controlnet; return ;;
    *vae*) echo vae; return ;;
    *tts*|*voice*) echo tts; return ;;
  esac

  # Fallback by size
  if   [ "$size" -lt 10485760 ];   then echo embedding
  elif [ "$size" -lt 524288000 ];  then echo lora
  elif [ "$size" -lt 2147483648 ]; then echo small_model
  elif [ "$size" -lt 8589934592 ]; then echo base_checkpoint
  else                                  echo huge_model
  fi
}

ts="$(date -Iseconds)"
jline type=element name=chain depth=0 \
  attributes="$(python3 -c "
import json, sys
print(json.dumps({'schema':'model_index_v0','ts':'$ts','roots':sys.argv[1:]}, sort_keys=True, separators=(',',':')))
" "${ROOTS[@]}")"

for root in "${ROOTS[@]}"; do
  [ -d "$root" ] || continue
  root_name="$(basename "$root")"

  total_files=$(find "$root" -maxdepth 5 -type f \( -name '*.safetensors' -o -name '*.ckpt' -o -name '*.pt' -o -name '*.pth' -o -name '*.gguf' -o -name '*.bin' -o -name '*.onnx' -o -name '*.lora' \) -not -path '*/.git/*' 2>/dev/null | wc -l | tr -d ' ')
  total_size_kb=$(du -sk --exclude='.git' --exclude='lfs' "$root" 2>/dev/null | awk '{print $1}')

  jline type=element name=root depth=1 parent=chain \
    attributes="$(python3 -c "import json; print(json.dumps({'path':'$root','name':'$root_name','total_files':$total_files,'total_size_kb':$total_size_kb}, sort_keys=True, separators=(',',':')))")"

  # Per top-level subdir summary
  for sub in $(find "$root" -maxdepth 1 -mindepth 1 -type d -not -name '.*' 2>/dev/null | sort); do
    sub_name="$(basename "$sub")"
    sub_files=$(find "$sub" -type f \( -name '*.safetensors' -o -name '*.ckpt' -o -name '*.pt' -o -name '*.pth' -o -name '*.gguf' -o -name '*.bin' -o -name '*.onnx' -o -name '*.lora' \) -not -path '*/.git/*' 2>/dev/null | wc -l | tr -d ' ')
    sub_size_kb=$(du -sk --exclude='.git' --exclude='lfs' "$sub" 2>/dev/null | awk '{print $1}')
    has_readme=0; [ -f "$sub/README.md" ] && has_readme=1
    has_config=0; [ -f "$sub/config.json" ] && has_config=1
    has_model_index=0; [ -f "$sub/model_index.json" ] && has_model_index=1

    jline type=element name=collection depth=2 parent=root \
      attributes="$(python3 -c "import json; print(json.dumps({'rel':'$sub_name','files':$sub_files,'size_kb':$sub_size_kb,'readme':bool($has_readme),'config':bool($has_config),'model_index':bool($has_model_index)}, sort_keys=True, separators=(',',':')))")"

    # Capture README snippet
    if [ -f "$sub/README.md" ]; then
      snippet="$(head -n 20 "$sub/README.md" 2>/dev/null | tr '\r' ' ')"
      jline type=text name=readme_snippet depth=3 parent=collection \
        data="$snippet" \
        attributes="$(python3 -c "import json; print(json.dumps({'collection':'$sub_name'}, sort_keys=True, separators=(',',':')))")"
    fi
  done

  # Per-file emit
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    rel="${f#$root/}"
    fname="$(basename "$f")"
    ext="${fname##*.}"
    size=$(stat -c %s "$f" 2>/dev/null || echo 0)
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    kind="$(classify "$rel" "$fname" "$size")"
    # Top-level subdir as collection key
    collection="${rel%%/*}"

    jline type=element name=model_file depth=2 parent=root \
      attributes="$(python3 -c "import json; print(json.dumps({'rel':'$rel','collection':'$collection','fname':'$fname','ext':'$ext','kind':'$kind','size':$size,'mtime':$mtime,'root':'$root_name'}, sort_keys=True, separators=(',',':')))")"
  done < <(find "$root" -type f \( -name '*.safetensors' -o -name '*.ckpt' -o -name '*.pt' -o -name '*.pth' -o -name '*.gguf' -o -name '*.bin' -o -name '*.onnx' -o -name '*.lora' \) -not -path '*/.git/*' -not -path '*/lfs/*' 2>/dev/null | sort)
done
