# /home/tom/models — DAG

Generated 2026-05-26. Classification source: prior scan (13 tools, 12 models, 1 lora, 1 class).

## Mermaid

```mermaid
flowchart LR
  %% inputs
  subgraph IN[INPUTS]
    IMG[image]; VID[video]; AUD[audio]; TXT[text]; PDF[pdf]
    POSE[pose-kpts]; CAM[camera/3D]; BOX[bbox-hint]
  end

  %% models
  subgraph MODELS
    M_DEPTH[apple_DepthPro]
    M_SEG[finegrain_box_segmenter]
    M_MFLOW[melodyflow-t24-30secs]
    M_MCLIP[metaclip-2-mt5]
    M_PEAV[pe-av-small]
    M_POSE[qualcomm_MediaPipe_Pose]
    M_QIE[Qwen_Image_Edit_2511]
    M_PX3D[TencentARC_Pixal3D]
    M_UV[ultravox-v0_7-glm-4_6]
    M_GEMMA[gemma-4-E4B-it]
    M_STG[SpaceTimeGPT]
    M_QTTS[Qwen3-TTS-12Hz-1.7B-CustomVoice]
    M_MAR[Marlin-2B-ungated]
  end

  %% loras + class
  L_BG[/flux2_klein_bg_remove_lora/]
  C_RSN[(claude-opus-reasoning-8.7k)]

  %% tools
  subgraph TOOLS
    T_CLIP[CLIP-Interrogator]
    T_CKEY[CorridorKey]
    T_FIRE[FireRed-Image-Edit]
    T_FSWAP[Flux2-Klein-Face-Swap]
    T_KOLOR[Kolors-Virtual-Try-On]
    T_LCV[LongCat-Video-Avatar-1.5]
    T_LTX[LTX2.3-Studio]
    T_MINE[MinerU]
    T_PX3D[Pixal3D]
    T_QPOSE[Qwen-AnyPose]
    T_QCAM[qwen-3d-camera]
    T_VBG[video-background-removal]
    T_VOX[Vocal-Isolator]
  end

  %% outputs
  subgraph OUT[OUTPUTS]
    O_IMG[image]; O_VID[video]; O_3D[3D mesh]; O_AUD[audio stem]
    O_MUS[music]; O_TXT[text]; O_EMB[embedding]; O_DEPTH[depth]
    O_MASK[mask]; O_KPTS[kpts]; O_MD[markdown]
  end

  IMG --> T_CLIP & T_FIRE & T_FSWAP & T_KOLOR & T_LCV & T_PX3D & T_QPOSE & T_QCAM & M_DEPTH & M_SEG & M_MCLIP & M_POSE & M_QIE & M_PX3D
  VID --> T_CKEY & T_VBG & M_PEAV & M_STG & M_MAR
  AUD --> T_VOX & T_LCV & M_UV & M_PEAV
  TXT --> T_LTX & T_FIRE & T_QPOSE & T_QCAM & M_QIE & M_MFLOW & M_GEMMA & M_UV & M_QTTS & M_MAR
  PDF --> T_MINE
  POSE --> T_QPOSE
  CAM --> T_QCAM
  BOX --> M_SEG

  T_FIRE -. uses .-> M_QIE
  T_QPOSE -. uses .-> M_QIE
  T_QCAM -. uses .-> M_QIE
  T_PX3D -. uses .-> M_PX3D
  T_FSWAP -. opt lora .-> L_BG

  M_DEPTH-->O_DEPTH; M_SEG-->O_MASK; M_MFLOW-->O_MUS; M_MCLIP-->O_EMB
  M_PEAV-->O_EMB; M_POSE-->O_KPTS; M_QIE-->O_IMG; M_PX3D-->O_3D
  M_UV-->O_TXT; M_GEMMA-->O_TXT
  M_STG-->O_TXT; M_MAR-->O_TXT; M_QTTS-->O_AUD

  T_CLIP-->O_TXT; T_CKEY-->O_VID; T_FIRE-->O_IMG; T_FSWAP-->O_IMG
  T_KOLOR-->O_IMG; T_LCV-->O_VID; T_LTX-->O_VID; T_MINE-->O_MD
  T_PX3D-->O_3D; T_QPOSE-->O_IMG; T_QCAM-->O_IMG; T_VBG-->O_VID; T_VOX-->O_AUD

  %% cross-tool pipelines (output feeds next tool)
  O_KPTS -.->|kpts→AnyPose| T_QPOSE
  O_TXT  -.->|prompt→T2V| T_LTX
  O_TXT  -.->|prompt→music| M_MFLOW
  O_MASK -.->|mask→bg-remove| T_VBG
  O_DEPTH-.->|depth→3D| T_PX3D
  O_IMG  -.->|portrait→avatar| T_LCV
  O_AUD  -.->|voice→avatar| T_LCV
  O_TXT  -.->|caption→TTS| M_QTTS
  O_TXT  -.->|video-caption→LLM| M_GEMMA
  O_AUD  -.->|TTS voice→avatar| T_LCV

  C_RSN -. ft corpus .-> M_GEMMA
```

## Example composed pipelines the DAG enables

| Goal | Path |
|---|---|
| Photo → talking avatar | IMG → T_LCV ← AUD (or M_UV synth) → O_VID |
| Photo → 3D asset | IMG → M_DEPTH → O_DEPTH → T_PX3D → O_3D |
| Pose-controlled edit | IMG → M_POSE → O_KPTS → T_QPOSE → O_IMG |
| Auto-prompt → T2V | IMG → T_CLIP → O_TXT → T_LTX → O_VID |
| Song splitter | AUD → T_VOX → O_AUD (stems) → M_MFLOW (remix) → O_MUS |
| Doc ingest → LLM | PDF → T_MINE → O_MD → M_GEMMA → O_TXT |
| Green-screen comp | VID → T_CKEY → O_VID → T_VBG → O_VID |
| Video → dense captions w/ timestamps | VID → M_MAR → O_TXT (scene/event spans) |
| Video → short description | VID → M_STG → O_TXT |
| Text → custom-voice speech | TXT → M_QTTS → O_AUD |
| LLM answer → spoken reply | TXT → M_GEMMA → O_TXT → M_QTTS → O_AUD |
| Video → narrated explainer | VID → M_MAR → O_TXT → M_GEMMA → O_TXT → M_QTTS → O_AUD → T_LCV (+ IMG) → O_VID |
| Find a moment in a video | VID + TXT (query) → M_MAR → O_TXT (start/end span) |

## Render

```
dot -Tsvg /home/tom/models/DAG.dot -o /home/tom/models/DAG.svg
dot -Tpng /home/tom/models/DAG.dot -o /home/tom/models/DAG.png
```
