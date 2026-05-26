#!/usr/bin/env bash
# Demo: run path_builder against every canonical pipeline mentioned in the
# gently team's table + the avatar critical-path subchains. For each:
#   1. ranked search:  does our scoring pick the documented chain?
#   2. direct build:   emit the workflow JSON for the explicit chain
#
# Run: bash planning/demo_pipelines.sh           (full output, ~120 lines)
#      bash planning/demo_pipelines.sh --short   (one line per demo)

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PB="$DIR/path_builder.py"
SHORT=0
[ "${1:-}" = "--short" ] && SHORT=1

bold() { printf '\033[1m%s\033[0m' "$*"; }
dim()  { printf '\033[2m%s\033[0m' "$*"; }
ok()   { printf '\033[32m%s\033[0m' "$*"; }
fail() { printf '\033[31m%s\033[0m' "$*"; }

demo() {
  # demo "name" "src" "dst" "intent" "expected-chain-comma-separated"
  local name="$1" src="$2" dst="$3" intent="$4" expected="$5"
  IFS=',' read -ra exp_arr <<<"$expected"
  echo
  echo "─────────────────────────────────────────────────────────────────"
  bold "$name"
  echo
  echo "  query  : $src → $dst  intent='$intent'"
  echo -n "  canonical: "
  for i in "${!exp_arr[@]}"; do
    [ "$i" -gt 0 ] && printf ' → '
    printf '%s' "${exp_arr[$i]}"
  done
  echo

  # 1. ranked search — capture top 1
  local out top1
  out="$(python3 "$PB" rank "$src" "$dst" --intent "$intent" --top 3 2>/dev/null)"
  top1="$(printf '%s' "$out" | awk '/^\[ 0\]/{sub(/^\[ 0\] [^=]+=[0-9.]+[[:space:]]+/,""); print; exit}')"
  echo "  derived: $top1"

  # 2. match check — substring overlap is enough for the demo
  local match=1
  for step in "${exp_arr[@]}"; do
    if ! printf '%s' "$top1" | grep -qF "$step"; then match=0; break; fi
  done
  if [ "$match" = "1" ]; then
    echo -n "  result : "; ok "✓ derived chain contains all canonical steps"; echo
  else
    echo -n "  result : "; fail "✗ derived chain missing one or more canonical steps"; echo
    echo "$out" | head -5
  fi

  # 3. show full top-3 for context (unless --short)
  if [ "$SHORT" = "0" ]; then
    echo
    dim "  top 3 ranked:"; echo
    echo "$out" | awk '/^\[/' | head -3 | sed 's/^/    /'
  fi

  # 4. emit canonical workflow JSON (unless --short)
  if [ "$SHORT" = "0" ]; then
    echo
    dim "  workflow JSON for canonical chain:"; echo
    python3 "$PB" build "${exp_arr[@]}" --name "${name//[^a-z0-9]/-}" 2>/dev/null \
      | head -20 | sed 's/^/    /'
  fi
}

bold "MySpace++ path-builder demo — every pipeline at once"; echo
echo

# ---- the 9 gently example pipelines ----
demo "1. Live multilingual interpreter" \
     "AUDIO" "AUDIO" "translation language interpret speech" \
     "Automatic Speech Recognition,Translation,Text-to-Speech"

demo "2. Story → image → animation" \
     "TEXT" "VIDEO" "story image animate" \
     "Text Generation,Text-to-Image,Image-to-Video"

demo "3. Podcast from PDFs" \
     "DOC" "AUDIO" "summarize podcast speech" \
     "Document Question Answering,Summarization,Text-to-Speech"

demo "4. Reverse image search" \
     "IMAGE" "DOC" "image search retrieve similar" \
     "Image Feature Extraction,Visual Document Retrieval"

demo "5. Video summarizer" \
     "VIDEO" "TEXT" "summarize video describe" \
     "Video-Text-to-Text,Summarization"

demo "6. Multilingual document search" \
     "DOC" "TEXT" "translate retrieve search multilingual" \
     "Visual Document Retrieval,Document Question Answering,Translation"

demo "7. Voice command → 3D model" \
     "AUDIO" "3D" "speech voice describe model" \
     "Automatic Speech Recognition,Text Generation,Text-to-3D"

demo "8. Prompt → 3D animation" \
     "TEXT" "VIDEO" "image 3d generate animate" \
     "Text-to-Image,Image-to-3D,Image-to-Video"

demo "9. VLM reasoning agent" \
     "IMAGE" "LABEL" "vision reason classify image" \
     "Image-Text-to-Text,Text Classification"

# ---- avatar critical-path subchains ----
demo "A. LLM brain (TEXT → TEXT response)" \
     "TEXT" "TEXT" "generate respond chat brain" \
     "Text Generation"

demo "B. User voice → LLM text" \
     "AUDIO" "TEXT" "transcribe speech recognition" \
     "Automatic Speech Recognition"

demo "C. LLM text → spoken voice" \
     "TEXT" "AUDIO" "speech voice clone synthesize" \
     "Text-to-Speech"

demo "D. Still avatar photo → animation" \
     "IMAGE" "VIDEO" "animate avatar still motion" \
     "Image-to-Video"

demo "E. Voice → talking head (E5 collapse)" \
     "AUDIO" "VIDEO" "avatar lipsync talking head" \
     "Audio-Text-to-Text,Image-Text-to-Video"

demo "F. PDF → Spanish podcast (intent-driven Translation insert)" \
     "DOC" "AUDIO" "translation spanish podcast" \
     "Document Question Answering,Translation,Text-to-Speech"

# ---- Video-centric sub-pipelines (the YouTube-avatar use case) ----
echo
echo "════════════════════════════════════════════════════════════════════════"
bold "  VIDEO PIPELINES — YouTube-avatar use case"; echo
echo "════════════════════════════════════════════════════════════════════════"

demo "V1. Source video → spoken audio (re-narrate)" \
     "VIDEO" "AUDIO" "narrate transcribe speech voice" \
     "Video-Text-to-Text,Text-to-Speech"

demo "V2. Source video → final talking-avatar video (Era-5 collapse)" \
     "VIDEO" "VIDEO" "avatar lipsync talking transform" \
     "Video-Text-to-Text,Image-Text-to-Video"

demo "V3. Source video → 3D avatar reconstruction" \
     "VIDEO" "3D" "avatar reconstruct 3d model" \
     "Video-Text-to-Text,Text-to-3D"

demo "V4. Image-Text-to-Video (single-step modern avatar)" \
     "IMAGE" "VIDEO" "avatar reference instruction animate" \
     "Image-Text-to-Video"

demo "V5. Voice clone target text → cloned voice audio" \
     "TEXT" "AUDIO" "voice clone synthesize spoken" \
     "Text-to-Speech"

demo "V6. Source video → background extraction (matting)" \
     "VIDEO" "MASK" "background mask matte extract" \
     "Video-to-Video,Image Segmentation"

demo "V7. Text script → walking-body video (the gait half)" \
     "TEXT" "VIDEO" "walking body gait motion avatar" \
     "Text-to-Video"

echo
echo "════════════════════════════════════════════════════════════════════════"
bold "  FULL YOUTUBE-AVATAR CHAIN (built explicitly, not derived)"; echo
echo "════════════════════════════════════════════════════════════════════════"
echo
echo "The original ask: source YouTube video → transcribe → rewrite script →"
echo "clone voice → synthesize new audio → lipsync onto target video."
echo
echo "This chain crosses modalities: VIDEO → TEXT → TEXT → AUDIO → VIDEO."
echo "The trailing AUDIO → VIDEO step is the lipsync — modern open-vocab"
echo "videogen models accept audio implicitly via the Image-Text-to-Video"
echo "interface (the 'text' slot carries an instruction like 'lipsync to:"
echo "<audio_path>'); strict HF taxonomy doesn't have an Audio+Image→Video"
echo "task, so the validator will flag the AUDIO→VIDEO edge as 'broken'"
echo "even though Wav2Lip/MuseTalk/SadTalker make it work in practice."
echo
dim "  build YouTube-avatar workflow JSON:"; echo
python3 "$PB" build \
  "Video-Text-to-Text" \
  "Text Generation" \
  "Text-to-Speech" \
  "Image-Text-to-Video" \
  --name "youtube-avatar" \
  --description "Source video → re-narrated talking-avatar video" 2>&1 \
  | sed 's/^/    /'
echo
echo "─────────────────────────────────────────────────────────────────"
bold "done."; echo
