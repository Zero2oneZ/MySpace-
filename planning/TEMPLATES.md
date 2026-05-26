# TEMPLATES.md — Claude-authored workflow library

> Companion to `DAG.md` (per-opcode interface design) and
> `DAG_CROSS.md` (successor predictions). This doc lists the 53
> rich workflow templates Claude authored against the seeded library
> (`capability_cards` + `gui_cards` + `path_builder` chains). Each
> template is a reusable recipe for one primary opcode, with multi-
> step orchestration, branch retry loops, optional HITL approval
> gates, and fallback model lists.
>
> Regenerate with:
> ```
> python3 planning/templates_summary.py > planning/TEMPLATES.md
> ```

## Library stats


- **Templates:** 53 (one per opcode)
- **With `__BRANCH__` retry loops:** 53 (100%)
- **With HITL approval gates:** 28 (53%)
- **With fallback model lists:** 53 (100%)
- **Average steps per template:** 4.5
- **Total steps across library:** 237
- **Total branch nodes:** 61

## Step-count distribution

| Steps | Templates |
|---|---|
| 3 | ██████████ 10 |
| 4 | ██████████████████ 18 |
| 5 | ██████████████████ 18 |
| 6 | ████ 4 |
| 7 | ███ 3 |

---

## Templates by HF category

- **Multimodal** (10): [`any-to-any-omni-multimodal`](#any-to-any-omni-multimodal), [`talking-head-lipsync-from-image`](#talking-head-lipsync-from-image), [`audio-text-to-text-conversation`](#audio-text-to-text-conversation), [`document-qa-with-retrieval-grounding`](#document-qa-with-retrieval-grounding), [`avatar-edit-via-text-instruction`](#avatar-edit-via-text-instruction), [`avatar-image-describer`](#avatar-image-describer), [`avatar-photo-to-animated-video`](#avatar-photo-to-animated-video), [`video-clip-qa-with-grounding`](#video-clip-qa-with-grounding), [`visual-document-rag-pipeline`](#visual-document-rag-pipeline), [`visual-question-answering-grounded`](#visual-question-answering-grounded)
- **Computer Vision** (19): [`depth-estimation-standard`](#depth-estimation-standard), [`image-classification-with-confidence-gate`](#image-classification-with-confidence-gate), [`image-feature-extraction-rag-ready`](#image-feature-extraction-rag-ready), [`avatar-background-segmentation`](#avatar-background-segmentation), [`image-to-3d-avatar-from-photo`](#image-to-3d-avatar-from-photo), [`avatar-style-transfer-with-quality-loop`](#avatar-style-transfer-with-quality-loop), [`image-to-text-caption`](#image-to-text-caption), [`image-to-video-avatar-motion`](#image-to-video-avatar-motion), [`pose-keypoints-for-controlnet-video`](#pose-keypoints-for-controlnet-video), [`avatar-background-mask`](#avatar-background-mask), [`object-detection-face-body-locator`](#object-detection-face-body-locator), [`text-to-3d-avatar-asset`](#text-to-3d-avatar-asset), [`text-to-image-avatar-portrait`](#text-to-image-avatar-portrait), [`text-to-video-avatar-walks`](#text-to-video-avatar-walks), [`unconditional-image-sample`](#unconditional-image-sample), [`video-classification-motion-tagger`](#video-classification-motion-tagger), [`avatar-lipsync-video-to-video`](#avatar-lipsync-video-to-video), [`zero-shot-image-classify-with-rerank`](#zero-shot-image-classify-with-rerank), [`zero-shot-object-detection-extract`](#zero-shot-object-detection-extract)
- **Natural Language Processing** (12): [`text-feature-extraction-for-rag`](#text-feature-extraction-for-rag), [`fill-mask-cloze-completion`](#fill-mask-cloze-completion), [`qa-grounded-rag-with-quality-loop`](#qa-grounded-rag-with-quality-loop), [`sentence-similarity-dedup-check`](#sentence-similarity-dedup-check), [`chat-history-summarization`](#chat-history-summarization), [`table-qa-grounded`](#table-qa-grounded), [`text-classification-intent-router`](#text-classification-intent-router), [`prompted-text-generation-with-quality-loop`](#prompted-text-generation-with-quality-loop), [`rag-rerank-quality-loop`](#rag-rerank-quality-loop), [`token-classification-ner-grounding`](#token-classification-ner-grounding), [`multilingual-translate-with-backtranslation-qc`](#multilingual-translate-with-backtranslation-qc), [`zero-shot-intent-router`](#zero-shot-intent-router)
- **Audio** (6): [`audio-classification-gated-asr`](#audio-classification-gated-asr), [`audio-to-audio-enhance-and-convert`](#audio-to-audio-enhance-and-convert), [`voice-to-text-transcription`](#voice-to-text-transcription), [`text-to-audio-bgm`](#text-to-audio-bgm), [`voice-clone-tts-pipeline`](#voice-clone-tts-pipeline), [`realtime-voice-activity-gate`](#realtime-voice-activity-gate)
- **Tabular** (3): [`tabular-classification-with-validation`](#tabular-classification-with-validation), [`tabular-regression-with-validation`](#tabular-regression-with-validation), [`timeseries-forecast-with-validation`](#timeseries-forecast-with-validation)
- **Reinforcement Learning** (2): [`rlhf-policy-train-loop`](#rlhf-policy-train-loop), [`vla-robot-action-from-scene`](#vla-robot-action-from-scene)
- **Other** (1): [`graph-ml-node-classification`](#graph-ml-node-classification)

---

## Multimodal  (10 templates)

### `any-to-any-omni-multimodal`

_primary opcode: `Any-to-Any`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `any-to-any,omni,multimodal,endgame,L5,era-7`

Endgame multimodal workflow: accepts any combination of text, image, audio, or video and emits any requested modality through a single omni-model inference, with a pre-flight intent rewrite for clarity and a post-generation quality check that branches back on low scores. Human checkpoint gates external delivery of generated media.

**Steps:**

  0. `Text Generation`
     _Rewrite user intent into a precise omni-prompt naming required output modalities and constraints._
     candidates: `qwen2.5-7b-instruct`, `llama-3.1-8b-instruct`, `mistral-7b-instruct`, `phi-3-medium-instruct`
  1. `Any-to-Any`
     _Run single omni-model inference across all provided input modalities to produce requested outputs._
     candidates: `gpt-4o`, `gemini-2.0-flash`, `qwen2.5-omni-7b`, `chameleon-7b`, `janus-pro-7b`
  2. `Zero-Shot Classification`
     _Score outputs against intent, safety, and modality-match labels to detect low-quality generations._
     candidates: `bart-large-mnli`, `deberta-v3-large-mnli`, `qwen2.5-7b-instruct`, `nli-deberta-v3-base`
  3. **`__BRANCH__`** on `$quality_label` → `matches_intent`, `off_topic`, `modality_mismatch`, `unsafe`
     - `matches_intent` → goto=4
     - `off_topic` → goto=1, max_retries=3, mutate: append clarifying constraints to $rewritten_prompt
     - `modality_mismatch` → goto=1, max_retries=3, mutate: explicitly enumerate required output modalities in $rewritten_prompt
     - `unsafe` → goto=0, max_retries=2, mutate: rewrite intent to remove unsafe content and re-plan
     _Retry omni inference with a sharpened prompt if quality is low; otherwise proceed._
  4. `Text Generation` 🟧 **HITL**
     _Produce a human-readable preview summary describing each generated artifact for review._
     candidates: `qwen2.5-7b-instruct`, `llama-3.1-8b-instruct`, `mistral-7b-instruct`
     checkpoint: type=`y/n`  prompt: "Preview summary attached. Approve releasing the generated media to the user/outp"

**Preconditions (3):**
  - `at_least_one_input_modality_present` = `True`
  - `output_modalities_requested` = `>=1`
  - `omni_model_available_or_fallback_chain_resolvable` = `True`

**Fallbacks:**
  - `Any-to-Any`: `Image-Text-to-Text`, `Video-Text-to-Text`, `Audio-Text-to-Text`, `Text-to-Image`, `Text-to-Audio`, `Text-to-Video`
  - `Text-Generation`: `Image-Text-to-Text`
  - `Text-to-Image`: `Image-to-Image`
  - `Text-to-Audio`: `Text-to-Speech`
  - `Text-to-Video`: `Image-to-Video`

**Outputs:**
  - `omni_outputs` (`TEXT+IMAGE+AUDIO+VIDEO`)
  - `preview_summary` (`TEXT`)

### `talking-head-lipsync-from-image`

_primary opcode: `Audio-Image-to-Video`_   ·   6 step(s)  ·  **2 branches**  ·  **1 HITL**

_tags:_ `lipsync,talking-head,avatar,video-generation,portrait-animation`

Given a reference portrait image and a spoken audio clip, produce a lip-synced talking-head video. Runs an upstream quality gate on the audio (silence/noise detection) and a downstream sync-quality check with a retry branch before optional human approval.

**Steps:**

  0. `Audio Classification`
     _Gate: confirm input audio actually contains speech (not silence/music) before spending GPU on lipsync._
     candidates: `hf_hub:yamnet`, `hf_hub:ast`, `hf_hub:beats`, `hf_hub:vggish`
  1. **`__BRANCH__`** on `$audio_label` → `speech`, `music`, `silence`, `other`
     - `speech` → goto=2
     - `music` → goto=2, mutate: warn_user_non_speech_input
     - `silence` → goto=99
     - `other` → goto=2, mutate: warn_user_non_speech_input
     _Abort early if the audio is not speech._
  2. `Audio-Image-to-Video`
     _Drive the reference portrait with the audio to produce a lipsynced talking-head clip._
     candidates: `hedra`, `emo`, `hallo`, `musetalk`, `sadtalker`
  3. `Video Classification`
     _Automated sync-quality / artifact check on the generated clip (face present, mouth motion present, no severe artifacts)._
     candidates: `videomae-base`, `timesformer-base`, `internvideo2`, `x3d-m`
  4. **`__BRANCH__`** on `$qc_label` → `good`, `poor`, `artifacted`, `no_face`
     - `good` → goto=5
     - `poor` → goto=2, max_retries=3, mutate: escalate_model_tier
     - `artifacted` → goto=2, max_retries=3, mutate: escalate_model_tier
     - `no_face` → goto=99
     _Retry lipsync with a stronger model if the QC label says the output is poor._
  5. `Audio-Image-to-Video` 🟧 **HITL**
     _Final human approval before saving / sharing the talking-head video._
     candidates: `hedra`, `emo`, `musetalk`, `sadtalker`, `wav2lip`
     checkpoint: type=`y/n`  prompt: "Lipsync looks correct and on-identity — save and proceed?"

**Preconditions (4):**
  - `image_has_single_face` = `True`
  - `audio_contains_speech` = `True`
  - `min_audio_duration_s` = `0.5`
  - `max_audio_duration_s` = `120`

**Fallbacks:**
  - `Audio-Image-to-Video`: `Wav2Lip`, `SadTalker`, `MuseTalk`
  - `Audio Classification`: `hf_hub:yamnet`, `hf_hub:ast`
  - `Video Classification`: `videomae`, `timesformer`

**Outputs:**
  - `approved_video` (`VIDEO`)

### `audio-text-to-text-conversation`

_primary opcode: `Audio-Text-to-Text`_   ·   6 step(s)  ·  **2 branches**  ·  **1 HITL**

_tags:_ `audio,speech,conversation,multimodal,low-latency,voice-agent`

Low-latency spoken-conversation turn: takes a user's voice clip plus an optional text system prompt and emits a grounded text reply. Uses a single multimodal model to collapse VAD+ASR+LLM, with a quality-check retry loop and an ASR+LLM fallback chain when the omni model is unavailable.

**Steps:**

  0. `Audio Classification`
     _Gate: detect silence/noise vs. speech before spending tokens on the omni model._
     candidates: `hf_hub:yamnet`, `hf_hub:ast`, `hf_hub:beats`, `hf_hub:vggish`
  1. **`__BRANCH__`** on `$audio_class` → `label==silence`, `label==noise`, `default`
     - `label==silence` → goto=99
     - `label==noise` → goto=99
     - `default` → goto=2
     _If no speech detected, abort early with a clear error rather than hallucinating a transcript._
  2. `Audio-Text-to-Text`
     _Single-shot multimodal reply: consume voice + system prompt, emit grounded text._
     candidates: `Qwen2-Audio-7B-Instruct`, `Qwen-Audio-Chat`, `gpt-4o`, `gemini-1.5-pro`, `Qwen2.5-Omni-7B`
  3. `Text Classification`
     _Quality gate: score the reply for refusal, empty, off-topic, or hallucination._
     candidates: `hf_hub:facebook/bart-large-mnli`, `hf_hub:cross-encoder/nli-deberta-v3-base`, `hf_hub:MoritzLaurer/deberta-v3-large-zeroshot-v2.0`
  4. **`__BRANCH__`** on `$reply_quality` → `label==low_quality`, `label==refusal`, `default`
     - `label==low_quality` → goto=2, max_retries=3, mutate: lower temperature by 0.1 and append 'be specific and grounded in the a
     - `label==refusal` → goto=2, max_retries=1, mutate: rephrase $system_prompt to remove ambiguity
     - `default` → goto=5
     _Retry the omni step up to 3 times on low-quality reply; nudge temperature/system prompt on each retry._
  5. `Text Generation` 🟧 **HITL**
     _Optional refinement pass: tighten phrasing only when the audio implied a long answer._
     candidates: `Qwen2.5-7B-Instruct`, `Llama-3.1-8B-Instruct`, `Mistral-7B-Instruct-v0.3`, `gpt-4o-mini`
     checkpoint: type=`y/n`  prompt: "Send this reply to the user?"

**Preconditions (3):**
  - `audio_duration_seconds_max` = `60`
  - `audio_sample_rate_min_hz` = `16000`
  - `audio_format_in` = `['wav', 'mp3', 'flac', 'ogg', 'm4a']`

**Fallbacks:**
  - `Audio-Text-to-Text`: `Automatic Speech Recognition`, `Text Generation`
  - `Automatic Speech Recognition`: `Audio-Text-to-Text`
  - `Text Generation`: `Audio-Text-to-Text`

**Outputs:**
  - `final_text` (`TEXT`)

### `document-qa-with-retrieval-grounding`

_primary opcode: `Document Question Answering`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `docqa,rag,legal,paperwork,grounded,retrieval,layout-aware`

Answers a user question grounded in an uploaded document by first retrieving the most relevant pages/sections via Visual Document Retrieval, then running a DocQA model over only those passages, with a quality-gated retry that broadens retrieval if the answer is low-confidence. Optimized for legal/paperwork avatar variants where hallucinated answers carry real risk.

**Steps:**

  0. `Visual Document Retrieval`
     _Rank document pages/sections by relevance to the question so DocQA only sees grounded context._
     candidates: `colpali-v1.2`, `colqwen2`, `nomic-embed-multimodal`, `jina-clip-v2`, `bge-m3`
  1. `Document Question Answering`
     _Answer the question grounded in the top-ranked passages, preserving layout cues._
     candidates: `layoutlmv3`, `donut`, `pix2struct`, `qwen2.5-vl-7b`, `gpt-4o`
  2. **`__BRANCH__`** on `$draft_answer.confidence` → `low_or_ungrounded`, `ok`
     - `low_or_ungrounded` → goto=0, max_retries=3, mutate: expand retrieval top_k from 5 to 15 and lower similarity threshold by 
     - `ok` → goto=3
     _If the answer is unsupported or low-confidence, broaden retrieval and retry; otherwise pass through._
  3. `Document Question Answering` 🟧 **HITL**
     _Pass-through identity step that emits the final grounded answer with citations to source pages._
     candidates: `layoutlmv3`, `qwen2.5-vl-7b`, `gpt-4o`, `pix2struct`, `donut`
     checkpoint: type=`y/n`  prompt: "This answer will be saved/exported as a legal-style response. Approve the cited "

**Preconditions (3):**
  - `document_uploaded` = `True`
  - `question_non_empty` = `True`
  - `max_pages` = `200`

**Fallbacks:**
  - `Visual Document Retrieval`: `Document Question Answering`, `Image-Text-to-Text`
  - `Document Question Answering`: `Image-Text-to-Text`, `Visual Question Answering`

**Outputs:**
  - `final_answer` (`TEXT`)

### `avatar-edit-via-text-instruction`

_primary opcode: `Image-Text-to-Image`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `avatar,image-edit,instruct,text-driven,quality-loop`

Edit an avatar/source image according to a natural-language instruction (e.g. 'now wearing a hat', 'change shirt to blue'). Rewrites vague prompts into edit-friendly directives, generates the edit, runs a VQA-based quality check, and loops back on low-fidelity results before surfacing the image to the user.

**Steps:**

  0. `Text Generation`
     _Rewrite user instruction into a clear, edit-friendly directive that preserves identity._
     candidates: `Qwen/Qwen2.5-7B-Instruct`, `meta-llama/Llama-3.1-8B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `google/gemma-2-9b-it`
  1. `Image-Text-to-Image`
     _Apply the textual edit to the source image while preserving subject identity._
     candidates: `black-forest-labs/FLUX.1-Kontext-dev`, `Qwen/Qwen-Image-Edit`, `timbrooks/instruct-pix2pix`, `stabilityai/stable-diffusion-xl-refiner-1.0`
  2. `Visual Question Answering`
     _Ask a VQA model whether the edit was applied AND identity preserved; emit pass/fail._
     candidates: `Salesforce/blip2-flan-t5-xl`, `llava-hf/llava-1.5-7b-hf`, `Qwen/Qwen2-VL-7B-Instruct`, `HuggingFaceM4/idefics2-8b`
  3. **`__BRANCH__`** on `$quality_verdict` → `fail`, `pass`
     - `fail` → goto=0, max_retries=3, mutate: strengthen edit_directive: add 'preserve subject identity, keep face/p
     - `pass` → goto=4
     _If VQA judges the edit failed or identity drifted, retry with a stronger directive._
  4. `Image-Text-to-Image` 🟧 **HITL**
     _Surface the final image to the user for explicit accept/reject before saving._
     checkpoint: type=`y/n`  prompt: "Save this edited avatar? (Edits identity and appearance — confirm before persist"

**Preconditions (3):**
  - `input_image_present` = `True`
  - `min_image_resolution` = `256x256`
  - `prompt_nonempty` = `True`

**Fallbacks:**
  - `Image-Text-to-Image`: `Image-to-Image`, `Text-to-Image`
  - `Visual Question Answering`: `Image-Text-to-Text`
  - `Text Generation`: `Text2Text Generation`

**Outputs:**
  - `final_image` (`IMAGE`)

### `avatar-image-describer`

_primary opcode: `Image-Text-to-Text`_   ·   5 step(s)  ·  **1 branch**

_tags:_ `vision,vlm,avatar,describe,reason,multimodal`

Lets an avatar reason about an image the user just shared, with a quality gate that retries if the description is too short or evasive. Defaults to open-weight VLMs and falls back gracefully when closed APIs are unavailable.

**Steps:**

  0. `Image-Text-to-Text`
     _Generate grounded description / answer from image+prompt_
     candidates: `qwen-vl-max`, `llava-1.6-34b`, `internvl2-8b`, `pixtral-12b`, `gpt-4v`
  1. `Text Classification`
     _Classify draft quality (grounded | hallucinated | too-short | refusal)_
     candidates: `deberta-v3-base`, `roberta-large-mnli`, `bge-reranker-base`
  2. **`__BRANCH__`** on `$quality_label` → `grounded`, `hallucinated`, `too-short`, `refusal`
     - `grounded` → goto=4
     - `hallucinated` → goto=3, max_retries=3, mutate: prepend 'Only describe what is literally visible. No speculation.' to 
     - `too-short` → goto=3, max_retries=3, mutate: append ' Be specific: list objects, colors, spatial relations, any tex
     - `refusal` → goto=4
     _Retry with stricter prompt if quality is poor_
  3. `Image-Text-to-Text`
     _Regenerate with stricter prompt_
     candidates: `qwen-vl-max`, `llava-1.6-34b`, `internvl2-8b`, `pixtral-12b`, `gpt-4v`
  4. `Feature Extraction`
     _Embed final answer for downstream retrieval / memory_
     candidates: `bge-large-en-v1.5`, `e5-mistral-7b-instruct`, `stella-en-1.5b-v5`

**Preconditions (3):**
  - `image_present` = `True`
  - `text_prompt_nonempty` = `True`
  - `max_image_bytes` = `10485760`

**Fallbacks:**
  - `Image-Text-to-Text`: `Visual Question Answering`, `Image-to-Text`
  - `Feature Extraction`: `Image Feature Extraction`

**Outputs:**
  - `draft_text` (`TEXT`)
  - `answer_embedding` (`EMBEDDING`)

### `avatar-photo-to-animated-video`

_primary opcode: `Image-Text-to-Video`_   ·   7 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `avatar,video,animation,image-to-video,instruction-following,lipsync-adjacent`

Turn a reference photo plus a text instruction into a short animated avatar video. Refines the prompt first, runs the animator, and gates the final save behind a human checkpoint because video is expensive to ship.

**Steps:**

  0. `Image-Text-to-Text`
     _Describe the reference photo so the prompt-rewriter knows what subject it is animating._
     candidates: `qwen-vl`, `llava`, `internvl`, `pixtral`, `gpt-4v`
  1. `Image-Text-to-Text`
     _Rewrite the user instruction into a clean motion prompt grounded in the subject caption._
     candidates: `qwen-vl`, `llava`, `internvl`, `pixtral`, `gpt-4v`
  2. `Image Segmentation`
     _Produce a subject mask so the animator can preserve the background and isolate motion to the avatar._
     candidates: `mit-han-lab/mask2former`, `facebookresearch/maskrcnn-benchmark`, `mit-han-lab/unet`, `facebookresearch/fcn`
  3. `Image-Text-to-Video`
     _Generate the animated avatar video from the photo, refined prompt, and mask._
     candidates: `animateanyone`, `wan-animate`, `kling`, `hailuo`
  4. `Image-Text-to-Text`
     _Auto-score the draft video against the original instruction (sampled frames + caption check)._
     candidates: `qwen-vl`, `internvl`, `llava`, `gpt-4v`
  5. **`__BRANCH__`** on `$quality_report.score` → `score < 6`, `score >= 6`
     - `score < 6` → goto=1, max_retries=3, mutate: append to motion_prompt: emphasize the action, shorten duration, reduc
     - `score >= 6` → goto=6
     _If auto-score is low, retry generation with a tightened prompt; otherwise continue to human review._
  6. `Image-Text-to-Video` 🟧 **HITL**
     _Pass-through gate that holds the draft for the user before final save/export._
     candidates: `animateanyone`, `wan-animate`, `kling`, `hailuo`
     checkpoint: type=`y/n`  prompt: "Save and export this generated avatar video? Preview before approving."

**Preconditions (4):**
  - `input_image_present` = `True`
  - `input_image_face_detected` = `True`
  - `text_prompt_nonempty` = `True`
  - `gpu_vram_gb_min` = `16`

**Fallbacks:**
  - `Image-Text-to-Video`: `Image-to-Video`, `Text-to-Video`
  - `Image-Text-to-Text`: `Image-to-Text`
  - `Image Segmentation`: `Image-Text-to-Image`

**Outputs:**
  - `final_video` (`VIDEO`)

### `video-clip-qa-with-grounding`

_primary opcode: `Video-Text-to-Text`_   ·   5 step(s)  ·  **1 branch**

_tags:_ `video-qa,multimodal,grounding,avatar,conversation`

Answers a user's question about a video clip with grounded, faithful output. Transcribes audio for textual grounding, runs the video+question through a VLM, and self-checks the answer against the transcript before returning, retrying with a stronger model if grounding is weak.

**Steps:**

  0. `Automatic Speech Recognition`
     _Transcribe the clip's audio so the answer can be grounded against spoken content._
     candidates: `openai/whisper-large-v3`, `openai/whisper-medium`, `distil-whisper/distil-large-v3`, `nvidia/parakeet-tdt-1.1b`, `facebook/seamless-m4t-v2-large`
  1. `Video-Text-to-Text`
     _Answer the user's question about the clip using video frames plus the transcript as grounding._
     candidates: `google/gemini-1.5-pro`, `Qwen/Qwen2-VL-72B-Instruct`, `Qwen/Qwen2-VL-7B-Instruct`, `llava-hf/LLaVA-NeXT-Video-7B-hf`, `Apollo-LMMs/Apollo-7B`
  2. `Text Classification`
     _Score whether the answer is grounded in the transcript and visually plausible (label: grounded|weak|hallucinated)._
     candidates: `meta-llama/Llama-3.1-8B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `google/gemma-2-9b-it`, `Qwen/Qwen2.5-7B-Instruct`, `microsoft/Phi-3.5-mini-instruct`
  3. **`__BRANCH__`** on `$grounding_score` → `grounded`, `weak`, `hallucinated`
     - `grounded` → goto=4
     - `weak` → goto=1, max_retries=2, mutate: escalate_model_tier=true; prompt_prefix='Cite specific timestamps and 
     - `hallucinated` → goto=1, max_retries=3, mutate: escalate_model_tier=true; prompt_prefix='Answer ONLY using evidence vi
     _If grounding is weak, retry the VLM step with a stronger model and stricter prompt._
  4. `Text Generation`
     _Polish the validated answer into the avatar's conversational voice without altering factual content._
     candidates: `meta-llama/Llama-3.1-8B-Instruct`, `Qwen/Qwen2.5-7B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `google/gemma-2-9b-it`, `HuggingFaceH4/zephyr-7b-beta`

**Preconditions (2):**
  - `video_duration_max_s` = `600`
  - `video_has_audio_track` = `True`

**Fallbacks:**
  - `Video-Text-to-Text`: `Image-Text-to-Text`, `Visual Question Answering`
  - `Automatic Speech Recognition`: `Audio Classification`

**Outputs:**
  - `final_answer` (`TEXT`)

### `visual-document-rag-pipeline`

_primary opcode: `Visual Document Retrieval`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `rag,retrieval,visual-documents,colpali,knowledge-base,multimodal`

Retrieves relevant visual document pages (PDFs, slides, scans) from a knowledge base given a natural-language query, with a rewrite-and-retry quality loop to handle weak first-pass recall. Returns the top matching document(s) for downstream grounding or display.

**Steps:**

  0. `Visual Document Retrieval`
     _First-pass retrieval using the user's raw query_
     candidates: `vidore/colpali-v1.2`, `vidore/colqwen2-v1.0`, `vidore/colpali`, `tsystems/colqwen2-2b-v1.0`, `vidore/dse-qwen2-2b-mrl-v1`
  1. **`__BRANCH__`** on `$first_pass_hits.top_score` → `score < 0.55`, `score >= 0.55`
     - `score < 0.55` → goto=2, max_retries=3, mutate: expand query with synonyms, add domain terms from corpus titles, drop 
     - `score >= 0.55` → goto=3
     _If top-hit score is weak, rewrite the query and retry retrieval_
  2. `Translation`
     _Rewrite/expand the query for stronger semantic match (used as a generic text->text rewriter)_
     candidates: `qwen2.5-7b-instruct`, `mistral-7b-instruct-v0.3`, `llama-3.1-8b-instruct`, `phi-3.5-mini-instruct`, `gemma-2-9b-it`
  3. `Visual Document Retrieval`
     _Final retrieval pass returning the ranked document set_
     candidates: `vidore/colpali-v1.2`, `vidore/colqwen2-v1.0`, `vidore/colpali`, `tsystems/colqwen2-2b-v1.0`, `vidore/dse-qwen2-2b-mrl-v1`

**Preconditions (3):**
  - `index_exists` = `True`
  - `min_corpus_size` = `1`
  - `embeddings_available` = `True`

**Fallbacks:**
  - `Visual Document Retrieval`: `Document Question Answering`, `Image-Text-to-Text`

**Outputs:**
  - `final_hits` (`DOC`)

### `visual-question-answering-grounded`

_primary opcode: `Visual Question Answering`_   ·   5 step(s)  ·  **1 branch**

_tags:_ `vqa,vision-language,multimodal,grounding,image-understanding`

Answer a natural-language question about an image with grounded vision-language reasoning. Pre-captions the image to enrich context, runs VQA, and retries with a refined question if the answer is low-confidence or refuses.

**Steps:**

  0. `Image-to-Text`
     _Generate a dense caption to ground the VQA model and catch obvious image issues._
     candidates: `Salesforce/blip2-flan-t5-xl`, `Salesforce/blip-image-captioning-large`, `microsoft/git-large-coco`, `nlpconnect/vit-gpt2-image-captioning`
  1. `Visual Question Answering`
     _Answer the user question against the image, conditioned on the caption._
     candidates: `Salesforce/blip2-flan-t5-xl`, `llava-hf/llava-1.5-13b-hf`, `Salesforce/blip-vqa-capfilt-large`, `dandelin/vilt-b32-finetuned-vqa`, `microsoft/git-large-vqav2`
  2. `Text Classification`
     _Score answer confidence and detect refusals or empty outputs._
     candidates: `cross-encoder/nli-deberta-v3-base`, `facebook/bart-large-mnli`, `MoritzLaurer/deberta-v3-base-zeroshot-v2.0`
  3. **`__BRANCH__`** on `$answer_quality` → `low_confidence_or_refusal`, `acceptable`
     - `low_confidence_or_refusal` → goto=1, max_retries=2, mutate: rephrase question_text more concretely; add caption-derived entities; 
     - `acceptable` → goto=4
     _Retry with a rephrased question if quality is low; otherwise finalize._
  4. `Visual Question Answering`
     _Pass-through finalization step that emits the accepted answer._
     candidates: `passthrough:$vqa_answer`

**Preconditions (3):**
  - `image_provided` = `True`
  - `question_non_empty` = `True`
  - `image_max_mb` = `20`

**Fallbacks:**
  - `Visual Question Answering`: `Image-Text-to-Text`, `Image-to-Text`
  - `Image-to-Text`: `Image-Text-to-Text`

**Outputs:**
  - `final_answer` (`TEXT`)

---

## Computer Vision  (19 templates)

### `depth-estimation-standard`

_primary opcode: `Depth Estimation`_   ·   3 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `depth,3d,monocular,nerf,gaussian-splat,parallax,midas,depth-anything`

Estimate a dense depth map from a single image for downstream 3D-aware pipelines (NeRF, Gaussian splat, parallax). Runs a single monocular depth model with an automatic quality gate that retries on a stronger model if the output looks degenerate.

**Steps:**

  0. `Depth Estimation`
     _Run monocular depth estimation on the input image_
     candidates: `depth-anything-v2-large`, `depth-anything-v2-base`, `dpt-large`, `midas-v3.1`, `monodepth2`
  1. **`__BRANCH__`** on `$depth_map` → `low_variance_or_invalid`, `ok`
     - `low_variance_or_invalid` → goto=0, max_retries=2, mutate: escalate_model_candidate=depth-anything-v2-large
     - `ok` → goto=2
     _Retry with a stronger model if the depth map looks degenerate (flat / low-variance / NaN)_
  2. `Depth Estimation` 🟧 **HITL**
     _Pass-through finalize step (keeps output binding stable across retries)_
     candidates: `passthrough`
     checkpoint: type=`y/n`  prompt: "Save this depth map for downstream 3D / NeRF use?"

**Preconditions (3):**
  - `input_image_present` = `True`
  - `min_resolution_px` = `256`
  - `gpu_available` = `False`

**Fallbacks:**
  - `Depth Estimation`: `Image-to-Image`

**Outputs:**
  - `final_depth_map` (`DEPTH_MAP`)

### `image-classification-with-confidence-gate`

_primary opcode: `Image Classification`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `vision,classification,backbone,top-k,confidence-gate`

Classifies an input image into one or more labels using a vision backbone, then gates low-confidence predictions through a retry with a stronger model. Returns top-k labels with scores.

**Steps:**

  0. `Image Classification`
     _Run primary classifier on the input image and produce top-k labels with scores._
     candidates: `google/vit-base-patch16-224`, `microsoft/resnet-50`, `facebook/convnext-base-224`, `timm/vgg16.tv_in1k`, `timm/alexnet.tv_in1k`
  1. **`__BRANCH__`** on `$primary_labels` → `top1_score<0.70`, `top1_score>=0.70`
     - `top1_score<0.70` → goto=2, max_retries=3, mutate: swap_model_to_next_candidate
     - `top1_score>=0.70` → goto=3
     _If top-1 confidence is below threshold, retry with a stronger backbone._
  2. `Image Classification`
     _Retry classification with a higher-capacity model when confidence was low._
     candidates: `google/vit-large-patch16-224`, `facebook/convnext-large-224`, `microsoft/resnet-152`, `timm/eva02_large_patch14_448.mim_m38m_ft_in22k_in1k`, `timm/beit_large_patch16_224`
  3. `Image Classification`
     _Pass-through node that finalizes the chosen labels for downstream use._
     candidates: `google/vit-base-patch16-224`, `microsoft/resnet-50`, `facebook/convnext-base-224`

**Preconditions (2):**
  - `image_readable` = `True`
  - `min_resolution_px` = `64`

**Fallbacks:**
  - `Image Classification`: `Zero-Shot Image Classification`, `Image Feature Extraction`

**Outputs:**
  - `final_labels` (`LABEL`)

### `image-feature-extraction-rag-ready`

_primary opcode: `Image Feature Extraction`_   ·   3 step(s)  ·  **1 branch**

_tags:_ `embedding,vision,retrieval,similarity,backbone,dinov2`

Extract robust embeddings from an input image for retrieval, similarity search, and downstream conditioning. Includes a sanity-check on embedding norm with one retry on a stronger backbone if the vector looks degenerate.

**Steps:**

  0. `Image Feature Extraction`
     _Encode the input image into a fixed-dimensional embedding vector._
     candidates: `facebook/dinov2-base`, `facebook/dinov2-large`, `timm/resnet50.a1_in1k`, `openai/clip-vit-base-patch32`, `timm/vit_base_patch16_224.augreg_in21k`
  1. **`__BRANCH__`** on `$embedding` → `norm_below_threshold_or_nan`, `ok`
     - `norm_below_threshold_or_nan` → goto=0, max_retries=1, mutate: swap model_candidates[0] -> facebook/dinov2-large; ensure preprocessin
     - `ok` → goto=2
     _Retry with a stronger backbone if the embedding is degenerate (near-zero norm or NaN)._
  2. `Feature Extraction`
     _Optionally L2-normalize embedding for cosine similarity use downstream._
     candidates: `builtin/l2-normalize`

**Preconditions (2):**
  - `image_readable` = `True`
  - `min_resolution_px` = `64`

**Fallbacks:**
  - `Image Feature Extraction`: `Image Classification`, `Zero-Shot Image Classification`

**Outputs:**
  - `normalized_embedding` (`EMBEDDING`)

### `avatar-background-segmentation`

_primary opcode: `Image Segmentation`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `segmentation,mask,avatar,matting,preprocessing,compositing`

Separates an avatar from its background by producing a clean alpha-friendly mask, with an automatic quality gate that retries on weak coverage or fragmented masks before the result is used downstream for lipsync compositing.

**Steps:**

  0. `Image Segmentation`
     _Generate the initial foreground/avatar mask from the input image._
     candidates: `facebook/mask2former-swin-large-coco-instance`, `facebook/maskformer-swin-large-ade`, `nvidia/segformer-b5-finetuned-ade-640-640`, `facebookresearch/maskrcnn-benchmark`, `briaai/RMBG-1.4`
  1. `Image Feature Extraction`
     _Embed the mask to score coverage, edge sharpness, and fragmentation against a clean-matte prototype._
     candidates: `facebook/dinov2-large`, `facebook/dinov2-base`, `google/vit-large-patch16-384`, `microsoft/resnet-50`
  2. **`__BRANCH__`** on `$mask_quality_score` → `score < 0.7`, `score >= 0.7`
     - `score < 0.7` → goto=0, max_retries=3, mutate: promote_next_model_candidate; raise threshold by 0.05
     - `score >= 0.7` → goto=3
     _Retry segmentation with a stronger model if the mask is too weak or fragmented._
  3. `Image Segmentation` 🟧 **HITL**
     _Refine boundary precision with edge-aware matting before handing off to compositing._
     candidates: `briaai/RMBG-1.4`, `PeterL1n/RobustVideoMatting`, `facebook/mask2former-swin-large-coco-instance`
     checkpoint: type=`y/n`  prompt: "Mask looks clean enough to send to lipsync compositing?"

**Preconditions (3):**
  - `input_modality` = `IMAGE`
  - `min_resolution_px` = `256`
  - `max_resolution_px` = `4096`

**Fallbacks:**
  - `Image Segmentation`: `Image-to-Image`, `Image Feature Extraction`

**Outputs:**
  - `final_mask` (`MASK`)

### `image-to-3d-avatar-from-photo`

_primary opcode: `Image-to-3D`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `3d,avatar,image-to-3d,mesh,reconstruction,single-view`

Convert a single reference photo into a downloadable 3D avatar mesh. Pre-segments the subject, reconstructs geometry, runs a quality gate, and asks the user to confirm before exporting the asset.

**Steps:**

  0. `Image Segmentation`
     _Isolate the subject from the background so the 3D reconstruction is not contaminated by scene geometry._
     candidates: `mit-han-lab/mask2former`, `facebookresearch/maskrcnn-benchmark`, `mit-han-lab/unet`, `facebookresearch/fcn`
  1. `Image-to-3D`
     _Reconstruct a 3D mesh from the masked reference photo._
     candidates: `Hunyuan3D`, `InstantMesh`, `TripoSR`, `Zero123`
  2. `Image Classification`
     _Quality-gate the rendered mesh thumbnail to detect collapsed, hollow, or malformed reconstructions._
     candidates: `vit-base`, `resnet50`, `vgg16`
  3. **`__BRANCH__`** on `$quality_label` → `low_quality`, `acceptable`
     - `low_quality` → goto=1, max_retries=3, mutate: swap_to_next_model_candidate
     - `acceptable` → goto=4
     _Retry reconstruction with a different model if quality is low._
  4. `Image-to-3D` 🟧 **HITL**
     _Final export pass at user-requested resolution and format; passes through if step 1 already satisfies output_format._
     candidates: `Hunyuan3D`, `InstantMesh`, `TripoSR`, `Zero123`
     checkpoint: type=`y/n`  prompt: "Preview the 3D avatar — save and download this mesh?"

**Preconditions (3):**
  - `input_image_min_resolution` = `512`
  - `gpu_vram_gb_min` = `12`
  - `output_format_supported` = `['obj', 'glb', 'stl']`

**Fallbacks:**
  - `Image-to-3D`: `Zero123`, `TripoSR`, `InstantMesh`, `Hunyuan3D`
  - `Image Segmentation`: `mit-han-lab/mask2former`, `facebookresearch/maskrcnn-benchmark`, `mit-han-lab/unet`

**Outputs:**
  - `final_mesh` (`3D`)

### `avatar-style-transfer-with-quality-loop`

_primary opcode: `Image-to-Image`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `image-to-image,style-transfer,controlnet,avatar,refinement,quality-loop`

Refines or restyles an avatar frame via image-to-image generation with a quality-check loop that retries with adjusted strength if the output drifts too far from the source. Suitable for ControlNet-conditioned style transfer and frame refinement.

**Steps:**

  0. `Image-to-Image`
     _Restyle or refine the input avatar frame guided by prompt and optional ControlNet conditioning._
     candidates: `stabilityai/stable-diffusion-xl-refiner-1.0`, `lllyasviel/control_v11p_sd15_openpose`, `timbrooks/instruct-pix2pix`, `runwayml/stable-diffusion-v1-5`, `stabilityai/sdxl-turbo`
  1. `Image-Text-to-Text`
     _Score the styled image against the original for fidelity, prompt adherence, and artifact level (0-10)._
     candidates: `llava-hf/llava-1.5-13b-hf`, `Qwen/Qwen2-VL-7B-Instruct`, `openbmb/MiniCPM-V-2_6`, `HuggingFaceM4/idefics2-8b`, `llava-hf/llava-1.5-7b-hf`
  2. **`__BRANCH__`** on `$quality_score` → `score_lt_6`, `score_gte_6`
     - `score_lt_6` → goto=0, max_retries=3, mutate: reduce strength by 0.15 and append 'preserve identity, reduce artifact
     - `score_gte_6` → goto=3
     _Retry with reduced strength if quality is low; otherwise advance._
  3. `Image-to-Image` 🟧 **HITL**
     _Optional final pass for subtle polish at low strength once quality threshold met._
     candidates: `stabilityai/stable-diffusion-xl-refiner-1.0`, `runwayml/stable-diffusion-v1-5`, `timbrooks/instruct-pix2pix`
     checkpoint: type=`y/n`  prompt: "Save this styled avatar frame?"

**Preconditions (3):**
  - `input_image_present` = `True`
  - `prompt_non_empty` = `True`
  - `min_resolution` = `256`

**Fallbacks:**
  - `Image-to-Image`: `Image-Text-to-Image`
  - `Image-Text-to-Text`: `Image Classification`

**Outputs:**
  - `final_image` (`IMAGE`)

### `image-to-text-caption`

_primary opcode: `Image-to-Text`_   ·   5 step(s)  ·  **1 branch**

_tags:_ `captioning,vision,accessibility,grounding,retry-loop`

Captions an image and verifies the caption is grounded and non-trivial before returning. Used for accessibility, search indexing, and giving avatars visual context awareness during a conversation.

**Steps:**

  0. `Image-to-Text`
     _Generate an initial caption describing the image content._
     candidates: `Salesforce/blip2-opt-2.7b`, `Salesforce/blip-image-captioning-large`, `microsoft/git-large-coco`, `Salesforce/blip2-flan-t5-xl`, `openai/clip-vit-large-patch14`
  1. `Image-Text-to-Text`
     _Critique the caption against the image for groundedness, specificity, and hallucination._
     candidates: `llava-hf/llava-1.6-mistral-7b-hf`, `Qwen/Qwen2-VL-7B-Instruct`, `gpt-4o-mini`, `mistral-community/pixtral-12b`, `OpenGVLab/InternVL2-8B`
  2. **`__BRANCH__`** on `$critique` → `ok`, `hallucinated|too_generic|ungrounded`
     - `ok` → goto=4
     - `hallucinated|too_generic|ungrounded` → goto=3, max_retries=3, mutate: prepend caption prompt with critique feedback; raise model tier
     _Retry with stronger guidance if critique flags issues._
  3. `Image-Text-to-Text`
     _Regenerate caption using the critique as guidance._
     candidates: `Qwen/Qwen2-VL-7B-Instruct`, `llava-hf/llava-1.6-mistral-7b-hf`, `mistral-community/pixtral-12b`, `OpenGVLab/InternVL2-8B`, `Salesforce/blip2-flan-t5-xl`
  4. `Image-to-Text`
     _Finalize the verified caption for return._
     candidates: `Salesforce/blip2-opt-2.7b`, `Salesforce/blip-image-captioning-large`, `microsoft/git-large-coco`, `Salesforce/blip2-flan-t5-xl`, `openai/clip-vit-large-patch14`

**Preconditions (3):**
  - `image_readable` = `True`
  - `min_resolution_px` = `224`
  - `max_file_mb` = `20`

**Fallbacks:**
  - `Image-to-Text`: `Image-Text-to-Text`, `Visual Question Answering`

**Outputs:**
  - `caption` (`TEXT`)

### `image-to-video-avatar-motion`

_primary opcode: `Image-to-Video`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `avatar,animation,pre-lipsync,portrait,motion,video`

Animate a still avatar portrait into a short looping clip suitable as a pre-lipsync base layer. Quality-checks the motion and retries with a tamer noise level if the output looks distorted.

**Steps:**

  0. `Image Segmentation`
     _Isolate the avatar from background so motion stays clean and the composite holds._
     candidates: `mit-han-lab/mask2former`, `facebookresearch/maskrcnn-benchmark`, `facebookresearch/fcn`, `mit-han-lab/unet`
  1. `Image-to-Video`
     _Generate a short animated clip from the still portrait with subtle, natural motion._
     candidates: `stable_video_diffusion`, `animate_diff`, `hunyuan-video`, `wan-video`
  2. `Video Classification`
     _Score the clip for distortion, identity drift, and motion plausibility._
     candidates: `videomae`, `timesformer`, `x-clip`, `internvideo`
  3. **`__BRANCH__`** on `$quality_score` → `score_lt_0.6`, `score_gte_0.6`
     - `score_lt_0.6` → goto=1, max_retries=3, mutate: decrease noise_level by 0.15, clamp >= 0.1
     - `score_gte_0.6` → goto=4
     _Retry with reduced noise_level if quality score is too low._
  4. `Image-to-Video` 🟧 **HITL**
     _Pass-through finalization step that surfaces the approved clip for downstream consumers._
     candidates: `passthrough`
     checkpoint: type=`y/n`  prompt: "Save this animated avatar clip and proceed to lipsync?"

**Preconditions (3):**
  - `input_image_present` = `True`
  - `input_image_is_portrait` = `True`
  - `min_resolution_px` = `512`

**Fallbacks:**
  - `Image-to-Video`: `AnimateDiff`, `Stable Video Diffusion`, `Image-to-Image`
  - `Image Segmentation`: `Image-to-Image`
  - `Video Classification`: `Image-to-Text`

**Outputs:**
  - `final_clip` (`VIDEO`)
  - `avatar_mask` (`MASK`)

### `pose-keypoints-for-controlnet-video`

_primary opcode: `Keypoint Detection`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `pose,keypoints,skeleton,controlnet,openpose,dwpose,avatar,preprocessing`

Detects body/hand/face keypoints from a reference image to drive pose-conditioned video generation. Optionally pre-segments the subject so background noise doesn't pollute the skeleton fit.

**Steps:**

  0. `Image Segmentation`
     _Isolate the subject so keypoint fit isn't confused by background limbs/figures._
     candidates: `mit-han-lab/mask2former`, `facebookresearch/maskrcnn-benchmark`, `facebookresearch/fcn`, `mit-han-lab/unet`
  1. `Keypoint Detection`
     _Estimate body/hand/face keypoints from the masked subject._
     candidates: `dwpose`, `openpose`, `hrnet`, `deeppose`
  2. **`__BRANCH__`** on `$keypoints.quality` → `low_confidence`, `ok`
     - `low_confidence` → goto=1, max_retries=2, mutate: swap model_candidates[0] -> next; lower confidence_threshold by 0.1
     - `ok` → goto=3
     _Retry with a higher-recall model if too few/low-confidence keypoints were found._
  3. `Image-to-Image` 🟧 **HITL**
     _Render the keypoints as a ControlNet-style pose map ready for downstream video gen._
     candidates: `ControlNet`, `img2img`, `InstructPix2Pix`
     checkpoint: type=`y/n`  prompt: "Does the pose skeleton match the subject's actual pose? Approve before driving v"

**Preconditions (3):**
  - `input_modality` = `IMAGE`
  - `min_resolution_px` = `256`
  - `subject_visible` = `True`

**Fallbacks:**
  - `Keypoint Detection`: `Image Segmentation`, `Image-to-Image`
  - `Image Segmentation`: `Image-to-Image`

**Outputs:**
  - `keypoints` (`KEYPOINTS`)
  - `pose_map` (`IMAGE`)

### `avatar-background-mask`

_primary opcode: `Mask Generation`_   ·   3 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `mask,segmentation,background-removal,avatar,sam,compositing`

Generate a clean separation mask of an avatar from a source image so downstream steps can composite, recolor, or animate the subject without background bleed. Uses SAM-family models with a quality loop that re-runs at higher precision if coverage is poor.

**Steps:**

  0. `Mask Generation`
     _Produce subject mask isolating the avatar from background_
     candidates: `sam2`, `sam`, `grounded-sam`, `mobile-sam`, `u2net`
  1. **`__BRANCH__`** on `$raw_mask.quality` → `coverage<0.85 OR edge_iou<0.9`, `ok`
     - `coverage<0.85 OR edge_iou<0.9` → goto=0, max_retries=2, mutate: escalate model_candidate to next-best; raise confidence_threshold by 0
     - `ok` → goto=2
     _Re-run with stronger model if coverage/edges are poor_
  2. `Image-to-Image` 🟧 **HITL**
     _Apply mask to extract clean foreground (alpha matte composite)_
     candidates: `alpha-matting-pymatting`, `modnet`, `backgroundmattingv2`
     checkpoint: type=`y/n`  prompt: "Background cleanly removed and edges look natural?"

**Preconditions (3):**
  - `input_image_present` = `True`
  - `min_resolution_px` = `256`
  - `subject_visible` = `True`

**Fallbacks:**
  - `Mask Generation`: `Image Segmentation`, `Image-to-Image`

**Outputs:**
  - `raw_mask` (`MASK`)
  - `matted_avatar` (`IMAGE`)

### `object-detection-face-body-locator`

_primary opcode: `Object Detection`_   ·   7 step(s)  ·  **2 branches**

_tags:_ `object-detection,face,body,preprocessing,lipsync-prep,pose-prep,vision`

Locate faces and bodies in source frames with a fast detector, then validate detection quality before downstream lipsync or pose transfer. Falls back to a heavier detector if confidence is low.

**Steps:**

  0. `Object Detection`
     _Run fast detector to locate face/body bounding boxes in the source frame._
     candidates: `yolov8n`, `yolov8s`, `detr-resnet-50`, `fast-r-cnn`, `r-cnn`
  1. **`__BRANCH__`** on `$primary_detections` → `empty_or_low_confidence`, `ok`
     - `empty_or_low_confidence` → goto=2, max_retries=3, mutate: swap_to_next_model_candidate
     - `ok` → goto=3
     _If no boxes or low confidence, retry with a heavier model before giving up._
  2. `Object Detection`
     _Re-run detection with the next, heavier candidate model._
     candidates: `detr-resnet-101`, `detr-resnet-50`, `yolov8x`, `yolov8l`
  3. `Image-to-Text`
     _Caption the frame to sanity-check that detected labels match what is visually present._
     candidates: `BLIP-2`, `BLIP`, `CoCa`, `CLIP`
  4. **`__BRANCH__`** on `$frame_caption` → `label_caption_mismatch`, `consistent`
     - `label_caption_mismatch` → goto=5, max_retries=1
     - `consistent` → goto=6
     _If caption disagrees with detected labels, escalate to keypoint detection for cross-check._
  5. `Keypoint Detection`
     _Use pose keypoints as an independent witness for face/body presence and location._
     candidates: `dwpose`, `hrnet`, `openpose`, `deeppose`
  6. `Object Detection`
     _Emit final reconciled detections package for downstream lipsync/pose steps._
     candidates: `yolov8s`, `detr-resnet-50`, `yolov8n`

**Preconditions (2):**
  - `image_provided` = `True`
  - `min_image_resolution` = `256`

**Fallbacks:**
  - `Object Detection`: `Keypoint Detection`, `Image-to-Text`

**Outputs:**
  - `final_detections` (`BOXES`)
  - `final_detections` (`LABEL`)

### `text-to-3d-avatar-asset`

_primary opcode: `Text-to-3D`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `3d,text-to-3d,avatar,mesh,vr,game-asset,generation`

Generates a 3D mesh/asset from a natural-language description with a prompt-refinement pass and a human checkpoint before export. Designed for avatar geometry destined for VR or game-engine integration.

**Steps:**

  0. `Text Generation`
     _Rewrite the user's prompt into a detailed, geometry-friendly 3D description (style, topology hints, scale, materials)._
     candidates: `claude`, `gpt-4`, `qwen`, `mistral`, `llama`
  1. `Text-to-3D`
     _Generate the 3D asset from the refined prompt._
     candidates: `trellis-text2mesh`, `hf-dreamfusion`, `hf-magic3d`, `hf-wonder3d`
  2. **`__BRANCH__`** on `$mesh_draft` → `quality_low_or_invalid_mesh`, `ok`
     - `quality_low_or_invalid_mesh` → goto=1, max_retries=3, mutate: tighten prompt: add topology constraints, reduce ambiguity, lock style
     - `ok` → goto=3
     _If the mesh is broken or low quality, retry with a tightened prompt; otherwise continue to review._
  3. `Text-to-3D` 🟧 **HITL**
     _Final review of the generated 3D asset before export to VR / game engine._
     candidates: `trellis-text2mesh`, `hf-dreamfusion`, `hf-magic3d`, `hf-wonder3d`
     checkpoint: type=`y/n`  prompt: "Approve this 3D asset for export to your VR / game-engine pipeline?"

**Preconditions (3):**
  - `gpu_available` = `True`
  - `min_vram_gb` = `12`
  - `viewer_supports` = `['glb', 'obj', 'ply']`

**Fallbacks:**
  - `Text-to-3D`: `hf-wonder3d`, `trellis-text2mesh`, `hf-magic3d`
  - `Text Generation`: `mistral`, `qwen`, `llama`

**Outputs:**
  - `final_mesh` (`3D`)

### `text-to-image-avatar-portrait`

_primary opcode: `Text-to-Image`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `text-to-image,avatar,portrait,generation,quality-loop,diffusion`

Generate an avatar portrait from a text description with a prompt-rewrite step for quality, a safety/aesthetic check, and a retry loop. Includes a human checkpoint before the final image is saved or shipped downstream.

**Steps:**

  0. `Text Generation`
     _Rewrite the user's raw description into a richer image prompt (style, lighting, framing)._
     candidates: `claude-3-5-sonnet`, `gpt-4o-mini`, `llama-3.1-8b-instruct`, `mistral-7b-instruct`, `qwen2.5-7b-instruct`
  1. `Text-to-Image`
     _Render the avatar portrait from the refined prompt._
     candidates: `flux-dev`, `stable-diffusion-xl-base-1.0`, `stable-diffusion-v1-5`, `dall-e-3`, `imagen-3`
  2. `Image Classification`
     _Score the image for prompt adherence, NSFW, and aesthetic quality._
     candidates: `clip-vit-large-patch14`, `clip-vit-base-patch32`, `laion-aesthetic-predictor-v2`, `nsfw-detector-v1`
  3. **`__BRANCH__`** on `$quality_score` → `score < 0.6 or nsfw == true`, `score >= 0.6 and nsfw == false`
     - `score < 0.6 or nsfw == true` → goto=0, max_retries=3, mutate: strengthen subject focus, clarify style anchors, drop NSFW-triggering 
     - `score >= 0.6 and nsfw == false` → goto=4
     _Retry with a mutated prompt if quality is too low or unsafe._
  4. `Text-to-Image` 🟧 **HITL**
     _Pass-through bind of the approved image for final output (no regeneration)._
     candidates: `flux-dev`, `stable-diffusion-xl-base-1.0`, `stable-diffusion-v1-5`
     checkpoint: type=`y/n`  prompt: "Save this avatar portrait as the final result?"

**Preconditions (3):**
  - `prompt_not_empty` = `True`
  - `min_vram_gb` = `8`
  - `nsfw_filter_enabled` = `True`

**Fallbacks:**
  - `Text-to-Image`: `stable-diffusion-v1-5`, `flux-schnell`
  - `Text Generation`: `llama-3.1-8b-instruct`, `mistral-7b-instruct`
  - `Image Classification`: `clip-vit-base-patch32`

**Outputs:**
  - `final_image` (`IMAGE`)
  - `refined_prompt` (`TEXT`)

### `text-to-video-avatar-walks`

_primary opcode: `Text-to-Video`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `video,generation,avatar,gait,text-to-video,diffusion`

Generate a short video clip from a text prompt with a prompt-rewrite quality loop and a human checkpoint before saving. Optimized for avatar body/gait clips and short vignettes.

**Steps:**

  0. `Text Generation`
     _Rewrite the user prompt into a structured T2V cinematography brief (subject, action, camera, lighting, style, duration)._
     candidates: `claude-sonnet-4-6`, `gpt-4o-mini`, `qwen2.5-7b-instruct`, `llama-3.1-8b-instruct`, `mistral-7b-instruct`
  1. `Text-to-Video`
     _Generate the video clip from the rewritten cinematography brief._
     candidates: `veo-3`, `sora`, `cogvideox-5b`, `modelscope-t2v`, `makeavideo`
  2. `Video Classification`
     _Score the draft clip for prompt fidelity, motion coherence, and artifact level._
     candidates: `videomae-large`, `internvideo2`, `x-clip-large`, `vjepa-vitl`
  3. **`__BRANCH__`** on `$quality_score` → `score<0.6`, `score>=0.6`
     - `score<0.6` → goto=0, max_retries=3, mutate: tighten subject/action specificity, add negative prompt for warping an
     - `score>=0.6` → goto=4
     _Retry generation with a tightened prompt if quality is below threshold._
  4. `Text-to-Video` 🟧 **HITL**
     _Pass-through step to present the accepted draft to the user for final review._
     candidates: `veo-3`, `sora`, `cogvideox-5b`, `modelscope-t2v`, `makeavideo`
     checkpoint: type=`y/n`  prompt: "Save this generated video? Review for artifacts, identity drift, and prompt fide"

**Preconditions (3):**
  - `prompt_nonempty` = `True`
  - `max_duration_seconds` = `12`
  - `gpu_available` = `True`

**Fallbacks:**
  - `Text-to-Video`: `CogVideoX`, `ModelScope`
  - `Text Generation`: `llama-3.1-8b-instruct`, `mistral-7b-instruct`

**Outputs:**
  - `video_final` (`VIDEO`)

### `unconditional-image-sample`

_primary opcode: `Unconditional Image Generation`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `generative,diffusion,sampling,latent-space,exploration`

Sample an image from a generative prior without a text prompt — useful for exploring a model's latent space, generating reference art, or producing variation seeds. Includes a downstream quality filter that retries on low-quality samples.

**Steps:**

  0. `Unconditional Image Generation`
     _Sample a fresh image from the model's prior distribution_
     candidates: `stabilityai/stable-diffusion-2-1`, `stabilityai/sdxl-base-1.0`, `CompVis/ldm-celebahq-256`, `google/ddpm-celebahq-256`, `nvidia/stylegan3`
  1. `Image Classification`
     _Score the sample for recognizable content / artifact detection_
     candidates: `openai/clip-vit-large-patch14`, `google/vit-base-patch16-224`, `microsoft/resnet-50`, `facebook/convnext-base-224`
  2. **`__BRANCH__`** on `$quality_label` → `low_quality_or_noise`, `acceptable`
     - `low_quality_or_noise` → goto=0, max_retries=3, mutate: reseed_and_raise_guidance_scale
     - `acceptable` → goto=3
     _Retry sampling if the output is degenerate / low-quality_
  3. `Unconditional Image Generation` 🟧 **HITL**
     _Pass-through finalization step (no-op; binds sampled_image to output)_
     candidates: `passthrough`
     checkpoint: type=`y/n`  prompt: "Save this sampled image to your gallery?"

**Preconditions (2):**
  - `gpu_available` = `True`
  - `min_vram_gb` = `8`

**Fallbacks:**
  - `Unconditional Image Generation`: `Image-to-Image`
  - `Image Classification`: `Image Feature Extraction`

**Outputs:**
  - `final_image` (`IMAGE`)

### `video-classification-motion-tagger`

_primary opcode: `Video Classification`_   ·   3 step(s)  ·  **1 branch**

_tags:_ `video,classification,motion,tagging,asset-filtering,ner-grounding`

Classify source videos by motion type (e.g. walking, running, dancing) to filter and tag assets before reuse in avatar pipelines. Uses a quality check loop to retry with stronger models if confidence is low.

**Steps:**

  0. `Video Classification`
     _Classify the input video into a motion-type label with confidence score._
     candidates: `videomae-base-finetuned-kinetics`, `timesformer-base-finetuned-k400`, `slowfast-r50-8x8`, `i3d-rgb-kinetics-400`, `x-clip-base-patch32`
  1. **`__BRANCH__`** on `$raw_label.confidence` → `< 0.6`, `>= 0.6`
     - `< 0.6` → goto=0, max_retries=3, mutate: escalate_model_tier
     - `>= 0.6` → goto=2
     _If confidence is low, retry with a stronger model; otherwise continue._
  2. `Token Classification`
     _Extract named entities from the label string for downstream pronunciation/grounding._
     candidates: `gliner-large`, `bert-base-NER`, `spacy-en-core-web-trf`, `distilbert-base-cased-NER`, `roberta-large-ontonotes5`

**Preconditions (3):**
  - `input_video_present` = `True`
  - `min_video_duration_s` = `1`
  - `max_video_duration_s` = `300`

**Fallbacks:**
  - `Video Classification`: `Video-Text-to-Text`, `Image Classification`

**Outputs:**
  - `raw_label` (`LABEL`)
  - `label_tokens` (`LABEL_SEQ`)

### `avatar-lipsync-video-to-video`

_primary opcode: `Video-to-Video`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `lipsync,talking-head,avatar,audio-conditioned,video-to-video`

Audio-conditioned lipsync pipeline that takes a driving video and an audio track and produces a talking-face output, with a quality gate that retries on low lipsync confidence and a human checkpoint before saving the final clip. Designed as the core 'walks-and-talks' avatar step.

**Steps:**

  0. `Video Classification`
     _Confirm the source clip is a usable talking-head shot (face visible, mostly frontal, low motion blur)._
     candidates: `microsoft/xclip-base-patch32`, `facebook/timesformer-base-finetuned-k400`, `MCG-NJU/videomae-base-finetuned-kinetics`, `facebook/slowfast_r50`, `i3d-kinetics-400`
  1. `Video-to-Video`
     _Run audio-conditioned lipsync to drive the mouth/face from the audio track._
     candidates: `TMElyralab/MuseTalk`, `Rudrabha/Wav2Lip`, `OpenTalker/SadTalker`, `HumanAIGC/AnimateAnyone`, `runwayml/gen-2`
  2. `Video Classification`
     _Score lipsync quality / artifact level on the generated clip._
     candidates: `joaanna/syncnet_python`, `MCG-NJU/videomae-base-finetuned-kinetics`, `microsoft/xclip-base-patch32`, `facebook/timesformer-base-finetuned-k400`
  3. **`__BRANCH__`** on `$lipsync_quality` → `score<0.7`, `score>=0.7`
     - `score<0.7` → goto=1, max_retries=3, mutate: escalate to next model_candidate and raise audio_guidance
     - `score>=0.7` → goto=4
     _If lipsync quality is below threshold, retry generation with a stronger model / higher guidance._
  4. `Video-to-Video` 🟧 **HITL**
     _Optional polish pass — temporal smoothing / face restoration on the accepted lipsync clip._
     candidates: `sczhou/CodeFormer`, `TencentARC/GFPGAN`, `xinntao/Real-ESRGAN`, `HumanAIGC/AnimateAnyone`
     checkpoint: type=`y/n`  prompt: "Approve this lipsynced clip for saving / downstream use?"

**Preconditions (5):**
  - `input_video_present` = `True`
  - `audio_input_present` = `True`
  - `gpu_available` = `True`
  - `input_video_has_face` = `True`
  - `audio_duration_le_video_duration` = `True`

**Fallbacks:**
  - `Video-to-Video`: `Image-to-Video`, `Text-to-Video`
  - `Video Classification`: `Image Classification`
  - `Automatic Speech Recognition`: `Audio Classification`

**Outputs:**
  - `polished_video` (`VIDEO`)

### `zero-shot-image-classify-with-rerank`

_primary opcode: `Zero-Shot Image Classification`_   ·   5 step(s)  ·  **2 branches**

_tags:_ `zero-shot,image,classification,clip,tagging,asset-filter,vision-language`

Classify an image against a user-supplied label set without any training, then optionally rerank low-confidence results with a stronger vision-language model. Designed for asset filtering and on-the-fly tagging where labels change per project.

**Steps:**

  0. `Zero-Shot Image Classification`
     _Score the image against every candidate label and emit top-k with confidences._
     candidates: `openai/clip-vit-large-patch14`, `google/siglip-so400m-patch14-384`, `laion/CLIP-ViT-H-14-laion2B-s32B-b79K`, `openai/clip-vit-base-patch32`, `laion/CLIP-ViT-bigG-14-laion2B-39B-b160k`
  1. **`__BRANCH__`** on `$primary_label.confidence` → `confidence>=0.65 AND margin>=0.10`, `confidence<0.65 OR margin<0.10`
     - `confidence>=0.65 AND margin>=0.10` → goto=4
     - `confidence<0.65 OR margin<0.10` → goto=2, max_retries=1
     _If top confidence is low or top-2 margin is tight, escalate to a VLM rerank; otherwise accept._
  2. `Image-Text-to-Text`
     _Ask a VLM to pick the best label from the candidate set with a short justification._
     candidates: `Qwen/Qwen2-VL-7B-Instruct`, `llava-hf/llava-onevision-qwen2-7b-ov-hf`, `HuggingFaceM4/Idefics3-8B-Llama3`, `microsoft/Florence-2-large`, `Salesforce/blip2-flan-t5-xl`
  3. **`__BRANCH__`** on `$vlm_label` → `vlm_label.label==primary_label.label OR vlm_label.confidence>=0.75`, `vlm_label.label!=primary_label.label AND vlm_label.confidence<0.75`
     - `vlm_label.label==primary_label.label OR vlm_label.confidence>=0.75` → goto=4
     - `vlm_label.label!=primary_label.label AND vlm_label.confidence<0.75` → goto=4, mutate: set final_label=vlm_label; attach_disagreement_note=true
     _If the VLM disagrees materially with the zero-shot pick, request a human tiebreaker; otherwise accept VLM result._
  4. `Zero-Shot Image Classification`
     _Emit the final consolidated label record (passthrough/format step)._
     candidates: `openai/clip-vit-large-patch14`, `google/siglip-so400m-patch14-384`, `laion/CLIP-ViT-H-14-laion2B-s32B-b79K`

**Preconditions (3):**
  - `image_present` = `True`
  - `labels_nonempty` = `True`
  - `min_labels` = `2`

**Fallbacks:**
  - `Zero-Shot Image Classification`: `Image Classification`, `Image-Text-to-Text`, `Visual Question Answering`
  - `Image-Text-to-Text`: `Visual Question Answering`

**Outputs:**
  - `final_label` (`LABEL`)

### `zero-shot-object-detection-extract`

_primary opcode: `Zero-Shot Object Detection`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `vision,detection,zero-shot,grounding,asset-extraction`

Detect arbitrary objects in an image from a free-form text description, with a prompt-rewrite quality loop that retries with a sharpened phrase when no boxes meet the confidence threshold. Optimized for asset extraction without retraining.

**Steps:**

  0. `Zero-Shot Object Detection`
     _Run grounded detection with the user's text prompt against the input image._
     candidates: `IDEA-Research/grounding-dino-base`, `IDEA-Research/grounding-dino-tiny`, `google/owlv2-base-patch16-ensemble`, `google/owlvit-base-patch32`, `stevengrove/YOLO-World`
  1. **`__BRANCH__`** on `$boxes_raw` → `empty_or_low_confidence`, `has_boxes`
     - `empty_or_low_confidence` → goto=2, max_retries=3, mutate: rewrite prompt: add synonyms, drop adjectives, split compound phrases 
     - `has_boxes` → goto=3
     _If no boxes pass the confidence floor, rewrite the prompt and retry; otherwise continue._
  2. `Image-Text-to-Text`
     _Use a VLM to sharpen the detection prompt by describing what is actually visible in the image, then loop back._
     candidates: `Qwen/Qwen2.5-VL-7B-Instruct`, `llava-hf/llava-onevision-qwen2-7b-ov-hf`, `HuggingFaceM4/idefics3-8b-llama3`, `microsoft/Florence-2-large`
  3. `Zero-Shot Object Detection` 🟧 **HITL**
     _Final pass — filter, NMS, and emit clean boxes for downstream extraction._
     candidates: `IDEA-Research/grounding-dino-base`, `google/owlv2-base-patch16-ensemble`, `stevengrove/YOLO-World`
     checkpoint: type=`y/n`  prompt: "Boxes look correct on the overlay — accept and extract crops?"

**Preconditions (3):**
  - `image_present` = `True`
  - `text_prompt_nonempty` = `True`
  - `min_confidence` = `0.25`

**Fallbacks:**
  - `Zero-Shot Object Detection`: `Object Detection`, `Image-Text-to-Text`
  - `Image-Text-to-Text`: `Visual Question Answering`

**Outputs:**
  - `boxes_final` (`BOXES`)

---

## Natural Language Processing  (12 templates)

### `text-feature-extraction-for-rag`

_primary opcode: `Feature Extraction`_   ·   3 step(s)  ·  **1 branch**

_tags:_ `embedding,rag,retrieval,text,vector,knowledge-base`

Embed a text passage into a dense vector for RAG retrieval against the avatar's knowledge base. Single-step extraction with a quality check that retries with a stronger model if the embedding is degenerate (NaN, all-zero, or wrong dimensionality).

**Steps:**

  0. `Feature Extraction`
     _Embed the input text into a dense vector suitable for cosine-similarity retrieval._
     candidates: `BAAI/bge-large-en-v1.5`, `intfloat/e5-large-v2`, `sentence-transformers/all-MiniLM-L6-v2`, `dunzhang/stella_en_400M_v5`, `sentence-transformers/all-mpnet-base-v2`
  1. **`__BRANCH__`** on `$embedding` → `is_degenerate`, `is_valid`
     - `is_degenerate` → goto=0, max_retries=3, mutate: promote_to_next_model_candidate
     - `is_valid` → goto=2
     _Retry with a stronger model if the embedding is degenerate or malformed._
  2. `Feature Extraction`
     _Terminal no-op anchor — embedding is finalized and ready to return._
     candidates: `passthrough`

**Preconditions (2):**
  - `input_text_nonempty` = `True`
  - `max_input_tokens` = `8192`

**Fallbacks:**
  - `Feature Extraction`: `Sentence Similarity`

**Outputs:**
  - `embedding_final` (`EMBEDDING`)

### `fill-mask-cloze-completion`

_primary opcode: `Fill-Mask`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `fill-mask,mlm,cloze,bert,encoder,text-completion`

Completes [MASK] tokens in input text using a masked language model, with an optional embedding-based sanity check that re-runs with a stronger model if the top prediction's confidence proxy is weak. Useful as a building block for cloze tests, lexical substitution, and grammar repair.

**Steps:**

  0. `Fill-Mask`
     _Generate top-k fills for [MASK] tokens in the input text_
     candidates: `answerdotai/ModernBERT-base`, `microsoft/deberta-v3-base`, `FacebookAI/roberta-base`, `google-bert/bert-base-uncased`, `distilbert/distilbert-base-uncased`
  1. `Feature Extraction`
     _Embed the filled text to score semantic coherence vs the original masked prompt_
     candidates: `sentence-transformers/all-MiniLM-L6-v2`, `BAAI/bge-small-en-v1.5`, `intfloat/e5-small-v2`, `sentence-transformers/all-mpnet-base-v2`
  2. **`__BRANCH__`** on `$coherence_vec` → `cosine_to_context<0.55`, `cosine_to_context>=0.55`
     - `cosine_to_context<0.55` → goto=0, max_retries=3, mutate: upgrade_model_tier:+1; widen top_k from 5 to 20
     - `cosine_to_context>=0.55` → goto=3
     _If coherence is low, retry Fill-Mask with a stronger model; otherwise accept_
  3. `Fill-Mask`
     _Finalize: emit the accepted completion as the output text_
     candidates: `answerdotai/ModernBERT-base`, `microsoft/deberta-v3-base`, `FacebookAI/roberta-base`

**Preconditions (2):**
  - `input_contains_mask_token` = `True`
  - `mask_count_max` = `8`

**Fallbacks:**
  - `Fill-Mask`: `Text Generation`, `Text2Text Generation`
  - `Feature Extraction`: `Sentence Similarity`

**Outputs:**
  - `final_text` (`TEXT`)

### `qa-grounded-rag-with-quality-loop`

_primary opcode: `Question Answering`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `qa,rag,grounded,quality-loop,conversational,docs,avatar-core`

Answer a user's question grounded in supplied context (RAG-style) with a self-grading quality loop that retries on low-confidence or off-context answers. Suitable as the conversational core of a docs-grounded avatar.

**Steps:**

  0. `Question Answering`
     _Produce a grounded answer from question + context._
     candidates: `mistralai/Mistral-7B-Instruct-v0.3`, `meta-llama/Llama-3.1-8B-Instruct`, `google/longformer-base-4096`, `deepset/roberta-base-squad2`, `bert-large-uncased-whole-word-masking-finetuned-squad`
  1. `Question Answering`
     _Self-grade: is the draft answer actually supported by the context? Return JSON {grounded: bool, confidence: 0-1, reason}_
     candidates: `mistralai/Mistral-7B-Instruct-v0.3`, `meta-llama/Llama-3.1-8B-Instruct`, `deepset/roberta-base-squad2`
  2. **`__BRANCH__`** on `$grade` → `grounded==true && confidence>=0.7`, `grounded==false || confidence<0.7`
     - `grounded==true && confidence>=0.7` → goto=3
     - `grounded==false || confidence<0.7` → goto=0, max_retries=3, mutate: prepend instruction: 'Answer ONLY using facts present verbatim in the 
     _If ungrounded or low confidence, retry the answer with a tightened prompt._
  3. `Question Answering`
     _Final polish — rewrite the validated answer in the conversational voice expected by the avatar._
     candidates: `mistralai/Mistral-7B-Instruct-v0.3`, `meta-llama/Llama-3.1-8B-Instruct`, `google/longformer-base-4096`

**Preconditions (3):**
  - `context_non_empty` = `True`
  - `question_non_empty` = `True`
  - `context_token_budget_max` = `8192`

**Fallbacks:**
  - `Question Answering`: `Text Generation`, `Summarization`
  - `Text Generation`: `Question Answering`

**Outputs:**
  - `answer_final` (`TEXT`)

### `sentence-similarity-dedup-check`

_primary opcode: `Sentence Similarity`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `embedding,similarity,dedup,memory-recall,semantic-search`

Compares two embeddings to determine semantic similarity, used for deduplication and memory recall in avatar systems. Branches on low-confidence scores to re-embed with a stronger model before final scoring.

**Steps:**

  0. `Sentence Similarity`
     _Compute cosine similarity between the two input embeddings_
     candidates: `sentence-transformers/all-mpnet-base-v2`, `BAAI/bge-large-en-v1.5`, `intfloat/e5-large-v2`, `princeton-nlp/sup-simcse-roberta-large`, `sentence-transformers/all-MiniLM-L6-v2`
  1. **`__BRANCH__`** on `$sim_score` → `in_ambiguous_band_0.45_to_0.65`, `clear_match_or_clear_miss`
     - `in_ambiguous_band_0.45_to_0.65` → goto=2, max_retries=2, mutate: upgrade_embedding_model
     - `clear_match_or_clear_miss` → goto=3
     _Re-embed with stronger model if score lands in ambiguous mid-range_
  2. `Feature Extraction`
     _Re-embed both inputs with a stronger model to disambiguate_
     candidates: `BAAI/bge-large-en-v1.5`, `intfloat/e5-mistral-7b-instruct`, `nvidia/NV-Embed-v2`, `Salesforce/SFR-Embedding-2_R`
  3. `Sentence Similarity`
     _Final scoring pass on refined embeddings (or pass-through if clear)_
     candidates: `BAAI/bge-large-en-v1.5`, `sentence-transformers/all-mpnet-base-v2`, `intfloat/e5-large-v2`

**Preconditions (2):**
  - `embeddings_same_dim` = `True`
  - `embeddings_normalized` = `True`

**Fallbacks:**
  - `Sentence Similarity`: `Feature Extraction`, `Text Classification`

**Outputs:**
  - `final_score` (`SCALAR`)

### `chat-history-summarization`

_primary opcode: `Summarization`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `summarization,memory,context-compression,chat,quality-loop`

Compress long conversation history into a short, faithful summary suitable for re-injection as context. Generates a draft summary, then runs a faithfulness/length check and retries with a tightened prompt if the draft drifts or exceeds the budget.

**Steps:**

  0. `Summarization`
     _Draft a compressed summary of the input conversation/text._
     candidates: `facebook/bart-large-cnn`, `google/pegasus-xsum`, `google/mt5-base`, `philschmid/flan-t5-base-samsum`, `sshleifer/distilbart-cnn-12-6`
  1. `Text Generation`
     _Score the draft for faithfulness and length-budget compliance vs. the source._
     candidates: `meta-llama/Llama-3.1-8B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `Qwen/Qwen2.5-7B-Instruct`, `microsoft/Phi-3.5-mini-instruct`, `google/gemma-2-9b-it`
  2. **`__BRANCH__`** on `$quality_report` → `fail`, `pass`
     - `fail` → goto=0, max_retries=3, mutate: prepend stricter directive: 'Be strictly faithful to the source. No ne
     - `pass` → goto=3
     _Retry summarization with stricter guidance if the draft is unfaithful or over budget._
  3. `Summarization`
     _Emit the accepted summary as the final compressed memory._
     candidates: `facebook/bart-large-cnn`, `google/pegasus-xsum`, `sshleifer/distilbart-cnn-12-6`

**Preconditions (3):**
  - `input_text_nonempty` = `True`
  - `input_text_token_count_gte` = `200`
  - `output_length_lte` = `512`

**Fallbacks:**
  - `Summarization`: `Text Generation`, `Text2Text Generation`
  - `Text Generation`: `Summarization`

**Outputs:**
  - `final_summary` (`TEXT`)

### `table-qa-grounded`

_primary opcode: `Table Question Answering`_   ·   5 step(s)  ·  **1 branch**

_tags:_ `tableqa,tabular,rag,business-automation,grounded`

Answer a natural-language question against a structured table by first normalizing the table, executing a TableQA model, then verifying the answer is grounded in actual cells before returning.

**Steps:**

  0. `Table Question Answering`
     _Run TableQA model over the table+question to produce a candidate answer with cited cells._
     candidates: `google/tapas-large-finetuned-wtq`, `microsoft/tapex-large-finetuned-wtq`, `google/tapas-base-finetuned-wikisql-supervised`, `Salesforce/CodeT5p-770m-py`, `openai/gpt-4o-mini`
  1. `Sentence Similarity`
     _Score how well candidate_answer is grounded by the cited table cells (cosine sim of answer vs. concatenated cited rows)._
     candidates: `sentence-transformers/all-mpnet-base-v2`, `BAAI/bge-large-en-v1.5`, `intfloat/e5-large-v2`, `sentence-transformers/all-MiniLM-L6-v2`
  2. **`__BRANCH__`** on `$grounding_score` → `score>=0.6`, `score<0.6`
     - `score>=0.6` → goto=4
     - `score<0.6` → goto=3, max_retries=3, mutate: rephrase question to be more specific and reference exact column names
     _Retry with a rewritten prompt if grounding is weak; otherwise accept._
  3. `Question Answering`
     _Rewrite the question using the table schema as context, then re-enter the TableQA step._
     candidates: `openai/gpt-4o-mini`, `mistralai/Mistral-7B-Instruct-v0.3`, `meta-llama/Llama-3.1-8B-Instruct`, `Qwen/Qwen2.5-7B-Instruct`
  4. `Summarization`
     _Format the grounded answer with a one-line citation of the source rows for the end user._
     candidates: `facebook/bart-large-cnn`, `google/pegasus-xsum`, `mistralai/Mistral-7B-Instruct-v0.3`, `openai/gpt-4o-mini`

**Preconditions (3):**
  - `table_nonempty` = `True`
  - `table_rows_max` = `50000`
  - `question_nonempty` = `True`

**Fallbacks:**
  - `Table Question Answering`: `Question Answering`, `Text Generation`
  - `Question Answering`: `Text Generation`

**Outputs:**
  - `final_answer` (`TEXT`)

### `text-classification-intent-router`

_primary opcode: `Text Classification`_   ·   5 step(s)  ·  **2 branches**

_tags:_ `routing,intent,classification,nlu,gating,l1`

Classify free-form user text into a fixed label set for fast intent routing before downstream LLM calls. Uses a small fast encoder with a confidence-gated fallback to a zero-shot classifier when the primary model is unsure.

**Steps:**

  0. `Text Classification`
     _Run the primary encoder classifier over the input and emit a label with confidence._
     candidates: `answerdotai/ModernBERT-base`, `microsoft/deberta-v3-base`, `distilbert-base-uncased-finetuned-sst-2-english`, `bert-base-uncased`, `roberta-base`
  1. **`__BRANCH__`** on `$primary_label` → `confidence>=0.75`, `confidence<0.75`
     - `confidence>=0.75` → goto=4
     - `confidence<0.75` → goto=2, max_retries=1
     _If primary classifier is low-confidence, fall back to zero-shot; otherwise accept._
  2. `Zero-Shot Classification`
     _Re-classify low-confidence inputs against the explicit label set using an NLI/instruct model._
     candidates: `facebook/bart-large-mnli`, `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`, `cross-encoder/nli-deberta-v3-base`, `Qwen/Qwen2.5-7B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`
  3. **`__BRANCH__`** on `$zeroshot_label` → `confidence>=0.6`, `confidence<0.6`
     - `confidence>=0.6` → goto=4
     - `confidence<0.6` → goto=0, max_retries=3, mutate: strip_punctuation_and_lowercase($input_text)
     _If zero-shot is also uncertain, retry primary once with normalized input._
  4. `Text Classification`
     _Emit the chosen label (passthrough resolution of primary vs zero-shot winner)._
     candidates: `answerdotai/ModernBERT-base`, `microsoft/deberta-v3-base`, `distilbert-base-uncased-finetuned-sst-2-english`, `bert-base-uncased`

**Preconditions (3):**
  - `input_text_nonempty` = `True`
  - `num_labels_min` = `2`
  - `labels_provided_or_finetuned` = `True`

**Fallbacks:**
  - `Text Classification`: `Zero-Shot Classification`, `Feature Extraction`

**Outputs:**
  - `final_label` (`LABEL`)

### `prompted-text-generation-with-quality-loop`

_primary opcode: `Text Generation`_   ·   6 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `text-generation,llm,brain,prompt-rewrite,quality-loop,avatar-reply`

Generates a polished textual response from a user prompt by first rewriting the prompt for clarity, generating candidate text, and quality-checking the result with an automatic retry loop. Designed as the brain step of an avatar reply pipeline.

**Steps:**

  0. `Summarization`
     _Rewrite/compress the raw prompt into a clear, well-scoped instruction._
     candidates: `facebook/bart-large-cnn`, `google/pegasus-xsum`, `google/mt5-base`, `huggingface/t5-small`
  1. `Text Generation`
     _Generate the response text from the cleaned prompt._
     candidates: `anthropic/claude-3-5-sonnet`, `openai/gpt-4o`, `meta-llama/Llama-3.1-70B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `Qwen/Qwen2.5-7B-Instruct`
  2. `Text Classification`
     _Classify the draft as acceptable / low-quality / unsafe._
     candidates: `modernbert-base`, `deberta-v3-base`, `distilbert-base-uncased`, `bert-base-uncased`
  3. **`__BRANCH__`** on `$quality_label` → `acceptable`, `low_quality`, `unsafe`
     - `acceptable` → goto=5
     - `low_quality` → goto=1, max_retries=3, mutate: raise temperature by 0.1 and append clarification asking for more spec
     - `unsafe` → goto=4
     _Loop back on low-quality output; stop on unsafe; pass on acceptable._
  4. `Text Generation` 🟧 **HITL**
     _Regenerate with stricter safety system prompt when flagged unsafe._
     candidates: `anthropic/claude-3-5-sonnet`, `openai/gpt-4o`, `meta-llama/Llama-Guard-3-8B`
     checkpoint: type=`y/n`  prompt: "Draft was flagged unsafe and regenerated. Approve sending this version?"
  5. `Summarization`
     _Optionally compress the final draft to fit downstream length budget._
     candidates: `facebook/bart-large-cnn`, `google/pegasus-xsum`, `google/mt5-base`

**Preconditions (2):**
  - `prompt_nonempty` = `True`
  - `max_length_within_model_limit` = `True`

**Fallbacks:**
  - `Text Generation`: `meta-llama/Llama-3.1-8B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `Qwen/Qwen2.5-7B-Instruct`
  - `Text Classification`: `distilbert-base-uncased-finetuned-sst-2-english`, `cross-encoder/nli-deberta-v3-base`
  - `Summarization`: `facebook/bart-large-cnn`, `google/pegasus-xsum`

**Outputs:**
  - `final_text` (`TEXT`)

### `rag-rerank-quality-loop`

_primary opcode: `Text Ranking`_   ·   3 step(s)  ·  **1 branch**

_tags:_ `rag,reranking,retrieval,quality-loop,colbert,bge`

Rerank top-k retrieved documents against a user query before stuffing them into an LLM context, with a quality gate that retries with a stronger model if the top score is too low. Designed for RAG pipelines where retrieval recall is high but precision needs sharpening.

**Steps:**

  0. `Text Ranking`
     _Rerank candidate documents against the query_
     candidates: `BAAI/bge-reranker-v2-m3`, `BAAI/bge-reranker-large`, `colbert-ir/colbertv2.0`, `cohere/rerank-english-v3.0`, `mixedbread-ai/mxbai-rerank-large-v1`
  1. **`__BRANCH__`** on `$ranked_initial.top_score` → `<0.5`, `>=0.5`
     - `<0.5` → goto=0, max_retries=3, mutate: escalate model_candidates: drop already-tried, prefer cross-encoder ov
     - `>=0.5` → goto=2
     _If top-1 score below threshold, retry with stronger reranker_
  2. `Text Ranking`
     _Pass-through node materializing the final ranked list_
     candidates: `identity`

**Preconditions (3):**
  - `documents_count_min` = `2`
  - `documents_count_max` = `200`
  - `query_nonempty` = `True`

**Fallbacks:**
  - `Text Ranking`: `Sentence Similarity`, `Feature Extraction`

**Outputs:**
  - `ranked_final` (`TEXT`)

### `token-classification-ner-grounding`

_primary opcode: `Token Classification`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `ner,token-classification,grounding,entities,pronunciation,rag`

Extracts named entities (persons, places, products, organizations) from input text to produce a labeled token sequence for pronunciation grounding and downstream RAG. Routes through a fast NER pass with a confidence-gated retry on a stronger model.

**Steps:**

  0. `Token Classification`
     _Fast NER pass to tag entities in input text._
     candidates: `urchade/gliner_large-v2.1`, `dslim/bert-base-NER`, `Jean-Baptiste/roberta-large-ner-english`, `spacy/en_core_web_trf`, `distilbert-base-cased-distilled-ner`
  1. **`__BRANCH__`** on `$ner_tags.avg_confidence` → `<0.75`, `>=0.75`
     - `<0.75` → goto=2, max_retries=3, mutate: swap_model_to_next_candidate
     - `>=0.75` → goto=3
     _If average entity confidence is low or zero entities found, retry with a stronger model._
  2. `Token Classification`
     _High-accuracy retry pass when initial confidence is insufficient._
     candidates: `urchade/gliner_large-v2.1`, `Jean-Baptiste/roberta-large-ner-english`, `xlm-roberta-large-finetuned-conll03-english`, `spacy/en_core_web_trf`
  3. `Token Classification`
     _Final canonicalization pass over the chosen tag set (idempotent merge of subword spans)._
     candidates: `urchade/gliner_large-v2.1`, `dslim/bert-base-NER`, `Jean-Baptiste/roberta-large-ner-english`

**Preconditions (2):**
  - `input_text_nonempty` = `True`
  - `max_input_chars` = `8000`

**Fallbacks:**
  - `Token Classification`: `Text Classification`, `Zero-Shot Classification`

**Outputs:**
  - `entities` (`LABEL_SEQ`)

### `multilingual-translate-with-backtranslation-qc`

_primary opcode: `Translation`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `translation,i18n,multilingual,quality-loop,back-translation`

Translate text into a target language with an optional back-translation quality check and retry loop. Defaults to a simple one-shot Translation call, but escalates to a higher-quality model when the round-trip similarity is low.

**Steps:**

  0. `Translation`
     _Translate the source text into the target language._
     candidates: `facebook/nllb-200-distilled-600M`, `facebook/m2m100_418M`, `Helsinki-NLP/opus-mt`, `facebook/nllb-200-3.3B`, `google/madlad400-3b-mt`
  1. `Translation`
     _Back-translate the output to source language for quality verification._
     candidates: `facebook/nllb-200-distilled-600M`, `facebook/m2m100_418M`, `Helsinki-NLP/opus-mt`
  2. `Sentence Similarity`
     _Score semantic similarity between original and back-translation._
     candidates: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`, `sentence-transformers/LaBSE`, `sentence-transformers/distiluse-base-multilingual-cased-v2`
  3. **`__BRANCH__`** on `$similarity_score` → `<0.75`, `>=0.75`
     - `<0.75` → goto=0, max_retries=2, mutate: escalate_model_candidate
     - `>=0.75` → goto=4
     _Retry with stronger model if similarity is low._
  4. `Translation` 🟧 **HITL**
     _Pass-through finalization step (no-op anchor for output binding)._
     candidates: `identity`
     checkpoint: type=`y/n`  prompt: "Accept this translation for delivery?"

**Preconditions (2):**
  - `input_text_nonempty` = `True`
  - `target_language_supported` = `True`

**Fallbacks:**
  - `Translation`: `Text2Text Generation`, `Text Generation`
  - `Text2Text Generation`: `Text Generation`
  - `Sentence Similarity`: `Feature Extraction`, `Text Classification`

**Outputs:**
  - `final_translation` (`TEXT`)
  - `similarity_score` (`LABEL`)

### `zero-shot-intent-router`

_primary opcode: `Zero-Shot Classification`_   ·   7 step(s)  ·  **2 branches**  ·  **1 HITL**

_tags:_ `routing,intent,classification,zero-shot,nli,triage`

Routes free-form text into one of a caller-supplied label set without training a classifier. Includes a low-confidence retry that rewrites ambiguous inputs before re-classifying, with a final fallback to an LLM judge when zero-shot remains uncertain.

**Steps:**

  0. `Zero-Shot Classification`
     _Score candidate labels against the input text and pick the top label with a confidence score._
     candidates: `facebook/bart-large-mnli`, `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`, `cross-encoder/nli-deberta-v3-base`, `Qwen/Qwen2.5-7B-Instruct`, `sileod/deberta-v3-base-tasksource-nli`
  1. **`__BRANCH__`** on `$primary_label.confidence` → `<0.55`, `>=0.55`
     - `<0.55` → goto=2, max_retries=2, mutate: rewrite input_text to be more explicit about intent before re-running 
     - `>=0.55` → goto=4
     _If top-label confidence is below threshold, rewrite the input for clarity and retry; otherwise accept._
  2. `Text Generation`
     _Rewrite the ambiguous input into a clearer paraphrase that preserves user intent._
     candidates: `Qwen/Qwen2.5-7B-Instruct`, `meta-llama/Llama-3.1-8B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `google/gemma-2-9b-it`, `microsoft/Phi-3.5-mini-instruct`
  3. `Zero-Shot Classification`
     _Re-classify the rewritten text against the same label set._
     candidates: `facebook/bart-large-mnli`, `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`, `cross-encoder/nli-deberta-v3-base`, `Qwen/Qwen2.5-7B-Instruct`, `sileod/deberta-v3-base-tasksource-nli`
  4. **`__BRANCH__`** on `$primary_label.confidence` → `<0.55`, `>=0.55`
     - `<0.55` → goto=5
     - `>=0.55` → goto=6
     _After retries, if still low-confidence, escalate to LLM judge; otherwise emit._
  5. `Text Generation` 🟧 **HITL**
     _LLM judge selects best label from the candidate set with a short rationale when zero-shot is uncertain._
     candidates: `Qwen/Qwen2.5-7B-Instruct`, `meta-llama/Llama-3.1-8B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, `google/gemma-2-9b-it`, `microsoft/Phi-3.5-mini-instruct`
     checkpoint: type=`y/n`  prompt: "Zero-shot stayed below confidence threshold; LLM judge picked '$primary_label.la"
  6. `Zero-Shot Classification`
     _Emit the final routed label and confidence to downstream chain consumers._
     candidates: `facebook/bart-large-mnli`, `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`, `cross-encoder/nli-deberta-v3-base`, `Qwen/Qwen2.5-7B-Instruct`, `sileod/deberta-v3-base-tasksource-nli`

**Preconditions (4):**
  - `labels_provided` = `True`
  - `labels_min_count` = `2`
  - `labels_max_count` = `50`
  - `input_text_nonempty` = `True`

**Fallbacks:**
  - `Zero-Shot Classification`: `Text Classification`, `Text Generation`
  - `Text Generation`: `Text2Text Generation`

**Outputs:**
  - `final_label` (`LABEL`)

---

## Audio  (6 templates)

### `audio-classification-gated-asr`

_primary opcode: `Audio Classification`_   ·   4 step(s)  ·  **1 branch**

_tags:_ `audio,classification,event-detection,vad-gate,asr-preflight`

Classifies an input audio clip into event categories (silence/music/voice/noise) and gates downstream ASR. Low-confidence predictions trigger one retry with a stronger model before falling back to the raw label.

**Steps:**

  0. `Audio Classification`
     _Run primary event classifier on the input clip_
     candidates: `hf_hub:MIT/ast-finetuned-audioset-10-10-0.4593`, `hf_hub:google/yamnet`, `hf_hub:microsoft/BEATs-base`, `hf_hub:vggish`, `hf_hub:facebook/wav2vec2-base-960h`
  1. **`__BRANCH__`** on `$primary_label.confidence` → `<0.65`, `>=0.65`
     - `<0.65` → goto=2, max_retries=3, mutate: swap_model_candidate:next
     - `>=0.65` → goto=3
     _If primary classifier confidence is low, retry with a stronger model; else accept_
  2. `Audio Classification`
     _Retry classification with next-best model on the same audio_
     candidates: `hf_hub:microsoft/BEATs-base`, `hf_hub:MIT/ast-finetuned-audioset-10-10-0.4593`, `hf_hub:google/yamnet`, `hf_hub:vggish`
  3. `Audio Classification`
     _Emit final consolidated label (uses retry_label if it ran, else primary_label)_
     candidates: `hf_hub:MIT/ast-finetuned-audioset-10-10-0.4593`, `hf_hub:google/yamnet`, `hf_hub:microsoft/BEATs-base`

**Preconditions (4):**
  - `audio_duration_seconds_min` = `0.5`
  - `audio_duration_seconds_max` = `600`
  - `sample_rate_hz_min` = `8000`
  - `audio_format_in` = `['wav', 'mp3', 'flac', 'ogg', 'm4a']`

**Fallbacks:**
  - `Audio Classification`: `Audio-Text-to-Text`

**Outputs:**
  - `final_label` (`LABEL`)

### `audio-to-audio-enhance-and-convert`

_primary opcode: `Audio-to-Audio`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `audio,enhancement,voice-conversion,source-separation,denoise,rvc,demucs`

Enhance or transform an input audio signal via source separation, denoising, or voice conversion. Includes an automatic quality gate that retries with a stronger model if the output fails loudness/artifact checks.

**Steps:**

  0. `Audio Classification`
     _Detect content type (speech/music/mixed/silence) to pick the right enhancer._
     candidates: `hf_hub:yamnet`, `hf_hub:ast`, `hf_hub:beats`, `hf_hub:vggish`
  1. `Audio-to-Audio`
     _Run the primary enhancement / separation / voice-conversion pass._
     candidates: `hf/transformer-demucs`, `hf/transformer-rvc`, `hf/transformer-diffwave-style-enhancer`, `hf/transformer-uvr`
  2. `Audio Classification`
     _Quality gate — classify output for artifacts/clipping/silence regressions._
     candidates: `hf_hub:yamnet`, `hf_hub:ast`, `hf_hub:beats`
  3. **`__BRANCH__`** on `$quality_label` → `artifact|clipped|silence`, `clean|speech|music`
     - `artifact|clipped|silence` → goto=1, max_retries=3, mutate: escalate to next model_candidate and lower enhancement_level by 0.2
     - `clean|speech|music` → goto=4
     _Retry with a stronger enhancer if quality gate flags artifacts; otherwise proceed._
  4. `Audio-to-Audio` 🟧 **HITL**
     _Optional final normalization / vocoder polish pass._
     candidates: `hf/transformer-diffwave-style-enhancer`, `hf/transformer-demucs`, `hf/transformer-uvr`
     checkpoint: type=`y/n`  prompt: "Save this enhanced/converted audio?"

**Preconditions (3):**
  - `input_audio_present` = `True`
  - `input_duration_seconds_max` = `600`
  - `input_sample_rate_min` = `16000`

**Fallbacks:**
  - `Audio-to-Audio`: `Audio Classification`

**Outputs:**
  - `final_audio` (`AUDIO`)

### `voice-to-text-transcription`

_primary opcode: `Automatic Speech Recognition`_   ·   6 step(s)  ·  **2 branches**

_tags:_ `asr,speech-to-text,transcription,voice-input,whisper`

Transcribe spoken audio to text with a quality loop that detects low-confidence or empty transcripts and retries with a stronger model. Optimized for the user-question -> LLM-input path.

**Steps:**

  0. `Audio Classification`
     _Gate: confirm the clip actually contains speech before spending ASR cycles_
     candidates: `hf_hub:yamnet`, `hf_hub:ast`, `hf_hub:beats`, `hf_hub:vggish`
  1. **`__BRANCH__`** on `$audio_label` → `speech`, `non_speech`
     - `speech` → goto=2
     - `non_speech` → goto=5, mutate: set transcript = '' and mark skipped=true
     _Skip ASR entirely if the clip is silence/music with no voice_
  2. `Automatic Speech Recognition`
     _Transcribe speech audio to text_
     candidates: `openai/whisper-large-v3`, `distil-whisper/distil-large-v3`, `openai/whisper-medium`, `useful-sensors/moonshine`, `facebook/wav2vec2-large-960h`
  3. **`__BRANCH__`** on `$transcript` → `empty_or_too_short`, `ok`
     - `empty_or_too_short` → goto=2, max_retries=3, mutate: promote to next model_candidate (larger/more accurate) and disable VAD
     - `ok` → goto=4
     _Quality loop: retry with stronger model if transcript is empty or too short_
  4. `Audio-Text-to-Text`
     _Optional post-pass: clean disfluencies, punctuate, and correct domain terms using transcript + original audio_
     candidates: `Qwen/Qwen2-Audio-7B-Instruct`, `Qwen/Qwen-Audio-Chat`, `gpt-4o-audio-preview`, `gemini-2.0-flash`
  5. `Automatic Speech Recognition`
     _Terminal sink: emit final transcript variable (no-op for non-speech path)_
     candidates: `openai/whisper-large-v3`

**Preconditions (3):**
  - `audio_duration_seconds_max` = `1800`
  - `audio_has_speech` = `True`
  - `sample_rate_hz_min` = `16000`

**Fallbacks:**
  - `Automatic Speech Recognition`: `Audio-Text-to-Text`, `Audio Classification`

**Outputs:**
  - `transcript_clean` (`TEXT`)

### `text-to-audio-bgm`

_primary opcode: `Text-to-Audio`_   ·   5 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `audio,music,sfx,generation,avatar,background`

Generate background music or SFX from a text prompt, with an optional prompt-refinement step and a quality gate that retries if the output is too short or silent. Designed for avatar environment/vignette audio.

**Steps:**

  0. `Text Generation`
     _Refine user prompt into a richer audio-generation prompt (genre, mood, instruments, tempo)._
     candidates: `qwen2.5-7b-instruct`, `mistral-7b-instruct`, `llama-3.1-8b-instruct`, `gpt-4o-mini`, `claude-haiku-4-5`
  1. `Text-to-Audio`
     _Generate the audio clip from the refined prompt._
     candidates: `facebook/musicgen-large`, `facebook/musicgen-medium`, `stable-audio-open-1.0`, `audioldm2-large`, `facebook/audiogen-medium`
  2. `Audio Classification`
     _Quality gate: detect silence / off-genre / corrupt output._
     candidates: `facebook/ast-finetuned-audioset`, `MIT/ast-finetuned-audioset-10-10-0.4593`, `laion/clap-htsat-fused`
  3. **`__BRANCH__`** on `$audio_qc` → `silent_or_corrupt`, `off_genre`, `pass`
     - `silent_or_corrupt` → goto=1, max_retries=3, mutate: strengthen prompt: add explicit instrumentation, tempo bpm, and 'high-
     - `off_genre` → goto=0, max_retries=2, mutate: re-refine prompt anchoring genre keywords from user_prompt
     - `pass` → goto=4
     _Retry generation with a stronger prompt if QC fails._
  4. `Text-to-Audio` 🟧 **HITL**
     _Final passthrough step exposing the approved clip as the workflow output._
     candidates: `facebook/musicgen-large`, `stable-audio-open-1.0`, `audioldm2-large`
     checkpoint: type=`y/n`  prompt: "Save this audio clip to your project library?"

**Preconditions (2):**
  - `prompt_nonempty` = `True`
  - `duration_seconds_max` = `120`

**Fallbacks:**
  - `Text-to-Audio`: `MusicGen`, `AudioLDM`
  - `Text Generation`: `mistral-7b-instruct`, `qwen2.5-7b-instruct`
  - `Audio Classification`: `facebook/ast-finetuned-audioset`

**Outputs:**
  - `final_audio` (`AUDIO`)

### `voice-clone-tts-pipeline`

_primary opcode: `Text-to-Speech`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `tts,voice-clone,audio,avatar,speech-synthesis`

Converts text into high-quality spoken audio, optionally cloning a reference voice. Includes a quality loop that re-synthesizes if the output audio fails intelligibility/clarity checks before saving.

**Steps:**

  0. `Text-to-Speech`
     _Synthesize the input text into audio using the selected (or cloned) voice._
     candidates: `XTTS-v2`, `StyleTTS2`, `VITS`, `FastSpeech2`, `Piper`
  1. `Audio-Text-to-Text`
     _Transcribe the generated audio back to text for intelligibility verification._
     candidates: `whisper-large-v3`, `faster-whisper`, `distil-whisper`, `whisper-medium`
  2. **`__BRANCH__`** on `$transcript_check.similarity` → `similarity < 0.85`, `similarity >= 0.85`
     - `similarity < 0.85` → goto=0, max_retries=3, mutate: lower temperature; increase reference voice weight; chunk long text in
     - `similarity >= 0.85` → goto=3
     _Retry synthesis if transcribed text diverges too far from source (low intelligibility)._
  3. `Text-to-Speech` 🟧 **HITL**
     _Pass-through finalization step: tag and package validated audio for delivery._
     candidates: `XTTS-v2`, `StyleTTS2`, `VITS`, `FastSpeech2`, `Tacotron2`
     checkpoint: type=`y/n`  prompt: "Listen to the final audio. Does it sound correct and match the intended voice? S"

**Preconditions (3):**
  - `text_non_empty` = `True`
  - `text_max_chars` = `5000`
  - `voice_sample_min_seconds` = `6`

**Fallbacks:**
  - `Text-to-Speech`: `XTTS-v2`, `StyleTTS2`, `Piper`, `Coqui-TTS`
  - `Audio-Text-to-Text`: `whisper-large-v3`, `faster-whisper`, `distil-whisper`

**Outputs:**
  - `final_audio` (`AUDIO`)

### `realtime-voice-activity-gate`

_primary opcode: `Voice Activity Detection`_   ·   3 step(s)  ·  **1 branch**

_tags:_ `vad,realtime,audio,gating,streaming,preprocessing`

Realtime audio gate that detects speech segments in an incoming audio stream and emits a label sequence of (start, end, is_speech) spans. Used upstream of ASR/LLM to avoid waking the pipeline on silence or background noise.

**Steps:**

  0. `Voice Activity Detection`
     _Detect speech vs. non-speech spans in the input audio with a tuned threshold._
     candidates: `silero-vad`, `pyannote/voice-activity-detection`, `webrtc-vad`, `hf/whisper-vad`, `funasr/fsmn-vad`
  1. **`__BRANCH__`** on `$vad_labels.speech_ratio` → `<0.02`, `>0.95`, `ok`
     - `<0.02` → goto=0, max_retries=2, mutate: lower threshold by 0.1, lower confidence_threshold by 0.1
     - `>0.95` → goto=0, max_retries=2, mutate: raise threshold by 0.1, raise confidence_threshold by 0.1
     - `ok` → goto=2
     _If too few or too many speech frames detected, retry with relaxed/tightened threshold._
  2. `Voice Activity Detection`
     _Pass-through finalization step emitting the cleaned label sequence (no re-inference; merges adjacent spans under min_gap_
     candidates: `silero-vad`, `pyannote/voice-activity-detection`, `webrtc-vad`

**Preconditions (3):**
  - `audio_sample_rate_hz` = `16000`
  - `audio_mono` = `True`
  - `min_chunk_ms` = `30`

**Fallbacks:**
  - `Voice Activity Detection`: `silero-vad`, `webrtc-vad`, `pyannote-vad`

**Outputs:**
  - `vad_labels_final` (`LABEL_SEQ`)

---

## Tabular  (3 templates)

### `tabular-classification-with-validation`

_primary opcode: `Tabular Classification`_   ·   3 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `tabular,classification,xgboost,gbdt,structured-data,trading,automation`

Trains and applies a gradient-boosted tabular classifier with a built-in quality gate that retries with adjusted hyperparameters if validation accuracy is too low. Optimized for trading-bot and business-automation use cases where label reliability matters more than raw speed.

**Steps:**

  0. `Tabular Classification`
     _Train ensemble classifier on the input table and predict labels_
     candidates: `xgboost`, `lightgbm`, `catboost`, `tabpfn`, `sklearn/random-forest`
  1. **`__BRANCH__`** on `$prediction_result.validation_accuracy` → `< 0.75`, `>= 0.75`
     - `< 0.75` → goto=0, max_retries=3, mutate: increase num_trees by 50%, reduce learning_rate by half, try next mode
     - `>= 0.75` → goto=2
     _Retry with tuned hyperparameters if validation accuracy is below threshold_
  2. `Tabular Classification` 🟧 **HITL**
     _Emit final labels with confidence scores_
     candidates: `xgboost`, `lightgbm`, `catboost`, `tabpfn`, `sklearn/random-forest`
     checkpoint: type=`y/n`  prompt: "Validation accuracy is $prediction_result.validation_accuracy. Accept these labe"

**Preconditions (3):**
  - `input_has_target_column` = `True`
  - `min_rows` = `100`
  - `min_validation_accuracy` = `0.75`

**Fallbacks:**
  - `Tabular Classification`: `xgboost`, `lightgbm`, `catboost`, `tabpfn`

**Outputs:**
  - `final_labels` (`LABEL`)

### `tabular-regression-with-validation`

_primary opcode: `Tabular Regression`_   ·   5 step(s)  ·  **2 branches**

_tags:_ `tabular,regression,gradient-boosting,forecasting,xgboost,lightgbm,business-automation`

Predicts a continuous scalar target from tabular features using gradient-boosted ensembles, with an upstream tabular-classification probe to detect data quality issues and a retry loop on poor fit. Best for trading-signal regression, price forecasting, and business KPI prediction.

**Steps:**

  0. `Tabular Classification`
     _Probe data quality by classifying target into quantile bins; if class balance is degenerate, the regression will be unre_
     candidates: `lightgbm`, `xgboost`, `catboost`, `tabPFN`
  1. **`__BRANCH__`** on `$quality_probe` → `degenerate`, `healthy`
     - `degenerate` → goto=4, mutate: flag_low_confidence
     - `healthy` → goto=2
     _Abort early if probe shows degenerate target distribution_
  2. `Tabular Regression`
     _Fit gradient-boosted regressor and predict scalar target_
     candidates: `xgboost`, `lightgbm`, `catboost`, `tabPFN`
  3. **`__BRANCH__`** on `$prediction` → `r2_below_threshold`, `r2_acceptable`
     - `r2_below_threshold` → goto=2, max_retries=3, mutate: increase_regularization_reduce_max_depth
     - `r2_acceptable` → goto=4
     _Retry with stronger regularization if validation R² is poor_
  4. `Tabular Regression`
     _Finalize prediction output (passthrough or low-confidence flag)_
     candidates: `xgboost`, `lightgbm`, `catboost`

**Preconditions (3):**
  - `min_rows` = `100`
  - `target_column_specified` = `True`
  - `no_all_null_features` = `True`

**Fallbacks:**
  - `Tabular Regression`: `Tabular Classification`, `Feature Extraction`
  - `Tabular Classification`: `Tabular Regression`

**Outputs:**
  - `final_prediction` (`SCALAR`)

### `timeseries-forecast-with-validation`

_primary opcode: `Time Series Forecasting`_   ·   3 step(s)  ·  **1 branch**

_tags:_ `forecasting,timeseries,backtest,chronos,quality-loop`

Forecasts future values of a time series with an automatic holdout-validation loop that retries with a stronger model when MAPE exceeds threshold. Returns the forecast plus a backtest score for downstream confidence.

**Steps:**

  0. `Time Series Forecasting`
     _Backtest on holdout tail to estimate accuracy before committing to a forecast._
     candidates: `amazon/chronos-t5-small`, `google/timesfm-1.0-200m`, `hf_hub/n_beats`, `hf_hub/temporal_fusion_transformer`, `hf_hub/deepar`
  1. **`__BRANCH__`** on `$backtest_score` → `mape_gt_0_2`, `mape_le_0_2`
     - `mape_gt_0_2` → goto=0, max_retries=3, mutate: escalate_model_candidate: prefer larger Chronos/TimesFM variant and in
     - `mape_le_0_2` → goto=2
     _If holdout MAPE too high, retry with a stronger/larger foundation model before producing the real forecast._
  2. `Time Series Forecasting`
     _Produce the final forecast over the requested horizon using the validated model._
     candidates: `amazon/chronos-t5-small`, `google/timesfm-1.0-200m`, `hf_hub/temporal_fusion_transformer`, `hf_hub/n_beats`, `hf_hub/deepar`

**Preconditions (3):**
  - `min_history_points` = `50`
  - `regular_frequency` = `True`
  - `max_missing_ratio` = `0.1`

**Fallbacks:**
  - `Time Series Forecasting`: `Tabular Regression`

**Outputs:**
  - `forecast` (`TIMESERIES`)
  - `backtest_score` (`SCALAR`)

---

## Reinforcement Learning  (2 templates)

### `rlhf-policy-train-loop`

_primary opcode: `Reinforcement Learning`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `reinforcement-learning,rlhf,policy,ppo,alignment,gait-control`

Train an RL policy that maps environment STATE to ACTION, with a built-in evaluation gate that branches back to retrain with mutated hyperparameters when the reward is too low. Includes a human checkpoint before promoting a policy to downstream use.

**Steps:**

  0. `Reinforcement Learning`
     _Train initial policy from environment state to action._
     candidates: `ppo`, `sac`, `dqn`, `ddpg`, `alphago`
  1. `Reinforcement Learning`
     _Roll out the trained policy on held-out states to score it._
     candidates: `ppo`, `sac`, `dqn`, `ddpg`
  2. **`__BRANCH__`** on `$eval_score` → `below_min_reward_threshold`, `above_min_reward_threshold`
     - `below_min_reward_threshold` → goto=0, max_retries=3, mutate: decay epsilon by 0.5, halve learning_rate, double batch_size
     - `above_min_reward_threshold` → goto=3
     _Retrain with adjusted hyperparameters if eval reward is below threshold._
  3. `Reinforcement Learning` 🟧 **HITL**
     _Confirm the policy is ready to be promoted before downstream use._
     candidates: `ppo`, `sac`, `dqn`, `ddpg`, `alphago`
     checkpoint: type=`y/n`  prompt: "Promote this trained policy to downstream consumers (RLHF reward model / gait co"

**Preconditions (4):**
  - `state_schema_defined` = `True`
  - `reward_function_available` = `True`
  - `action_space_specified` = `True`
  - `min_reward_threshold` = `0.7`

**Fallbacks:**
  - `Reinforcement Learning`: `Reinforcement Learning`

**Outputs:**
  - `final_action` (`ACTION`)

### `vla-robot-action-from-scene`

_primary opcode: `Robotics`_   ·   4 step(s)  ·  **1 branch**  ·  **1 HITL**

_tags:_ `robotics,vla,embodied,action,safety-gated`

Vision-language-action chain that captions a scene, then conditions a VLA policy on the caption + raw image to emit a low-level robot action. Human checkpoint gates execution before the action is sent to physical hardware.

**Steps:**

  0. `Image-to-Text`
     _Caption the current scene to ground the VLA in linguistic context._
     candidates: `blip2-flan-t5-xl`, `llava-1.6-mistral-7b`, `blip-large`, `coca-vit-l-14`, `clip-interrogator`
  1. `Robotics`
     _Run the VLA policy on (image, instruction + caption) to predict the next robot action._
     candidates: `openvla-7b`, `octo-base`, `rt-2-x`, `pi-zero`, `helix-vla`
  2. **`__BRANCH__`** on `$candidate_action.confidence` → `<0.4`, `>=0.4`
     - `<0.4` → goto=0, max_retries=3, mutate: increase caption detail; widen instruction context
     - `>=0.4` → goto=3
     _Re-caption and retry if VLA confidence is low or action is null._
  3. `Robotics` 🟧 **HITL**
     _Final safety gate before the action is dispatched to the physical robot._
     candidates: `openvla-7b`, `octo-base`, `rt-2-x`
     checkpoint: type=`y/n`  prompt: "Approve sending this action to the robot? Review predicted motion + workspace st"

**Preconditions (3):**
  - `robot_emergency_stop_reachable` = `True`
  - `workspace_clear` = `True`
  - `image_resolution_min` = `224x224`

**Fallbacks:**
  - `Robotics`: `Image-Text-to-Text`
  - `Image-to-Text`: `Image-Text-to-Text`

**Outputs:**
  - `approved_action` (`ACTION`)

---

## Other  (1 templates)

### `graph-ml-node-classification`

_primary opcode: `Graph Machine Learning`_   ·   3 step(s)  ·  **1 branch**

_tags:_ `graph,gnn,node-classification,knowledge-graph,embeddings`

Train or run inference with a graph neural network on a user-supplied graph to produce node/edge labels alongside an enriched graph. Includes a quality-check branch that retries with a deeper model if validation accuracy is below threshold.

**Steps:**

  0. `Graph Machine Learning`
     _Run GNN forward pass to produce labeled graph and per-node labels_
     candidates: `graphormer`, `graphsage`, `gat`, `gcn`
  1. **`__BRANCH__`** on `$gnn_result.val_accuracy` → `<0.75`, `>=0.75`
     - `<0.75` → goto=0, max_retries=3, mutate: escalate model_candidate (gcn->gat->graphsage->graphormer); increase n
     - `>=0.75` → goto=2
     _Retry with stronger model if validation accuracy is low_
  2. `Feature Extraction`
     _Extract node embeddings from the trained graph for downstream RAG/retrieval_
     candidates: `bge-base-multilingual`, `sentence-transformers/all-MiniLM-L6-v2`, `e5-base-uncased`

**Preconditions (3):**
  - `input_graph_format` = `['graphml', 'gexf', 'json']`
  - `min_nodes` = `10`
  - `has_node_features` = `True`

**Fallbacks:**
  - `Graph Machine Learning`: `Feature Extraction`, `Tabular Classification`

**Outputs:**
  - `gnn_result` (`GRAPH`)
  - `gnn_result.labels` (`LABEL`)
  - `node_embeddings` (`EMBEDDING`)

---
