"""cc studio v2 — task-picker centric UI.

Defaults scope to CC_STUDIO_HOME on every launch. Assets land in
cc-studio/assets/{video,audio,images,models,datasets,renders,intermediate}.
GUI assembles itself based on the chosen task.

Layout (top → bottom):
  - Global header (refresh / clear / design — never changes)
  - Task picker (front door — grid of task cards)
  - When a task is picked: task panel (assets + suggested tools + actions)
  - When chat exists: chat history feed (scrolls)
  - When a shelf is open: shelf with own input at top
  - Bottom (always): target cell · shelf toggles · chat input
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

try:
    import requests
except ImportError:
    requests = None
    import urllib.request

# ---- paths -------------------------------------------------------------

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
CC_DB = Path(os.environ.get("CC_GLOBAL_DB", str(CC_HOME / "cc.db")))
CC_STUDIO_HOME = Path(os.environ.get("CC_STUDIO_HOME", str(Path.home() / "cc-studio")))
ASSETS_DIR = CC_STUDIO_HOME / "assets"
PROJECTS_DIR = CC_STUDIO_HOME / "projects"
WORKFLOWS_DIR = CC_STUDIO_HOME / "workflows"
TOOLS_DIR = CC_STUDIO_HOME / "tools"

ASSET_KINDS = ("video", "audio", "images", "models", "datasets", "renders", "intermediate")
for _d in (PROJECTS_DIR, ASSETS_DIR, WORKFLOWS_DIR, TOOLS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
for _k in ASSET_KINDS:
    (ASSETS_DIR / _k).mkdir(exist_ok=True)

# ---- chat backend env --------------------------------------------------

CHAT_FALLBACK_MODEL = os.environ.get("CC_CHAT_FALLBACK_MODEL", "kimi-k2.9:cloud")
CHAT_FALLBACK_MODEL_2 = os.environ.get("CC_CHAT_FALLBACK_MODEL_2", "kimi-k2.6:cloud")
OLLAMA_URL = os.environ.get("CC_OLLAMA_URL", "http://localhost:11434")
CLAUDE_TIMEOUT_S = int(os.environ.get("CC_CLAUDE_TIMEOUT", "300"))
OLLAMA_TIMEOUT_S = int(os.environ.get("CC_OLLAMA_TIMEOUT", "300"))

# ---- task catalog ------------------------------------------------------
# id          icon  label             tags-match           asset-kind
TASKS = [
    ("video_avatar",   "🎥", "Avatar / Video",  ["video", "lipsync", "avatar", "render", "ffmpeg"], "video"),
    ("audio_vocal",    "🎤", "Vocal / Audio",   ["audio", "vocal", "tts", "voice", "transcribe", "stt"], "audio"),
    ("image_studio",   "🖼️", "Image Studio",   ["image", "sd", "pose", "background", "stable-diffusion"], "images"),
    ("agent_chat",     "🤖", "Agent / Chat",   [], None),
    ("dataset_train",  "📊", "Dataset / LoRA", ["dataset", "train", "lora", "finetune"], "datasets"),
    ("design_tool",    "🛠️", "Design Tool",    [], None),
    ("custom",         "🌐", "Custom",         [], None),
]
TASKS_BY_ID = {t[0]: t for t in TASKS}

# ---- db helpers --------------------------------------------------------

def db():
    c = sqlite3.connect(str(CC_DB))
    c.row_factory = sqlite3.Row
    return c


@st.cache_data(ttl=5)
def load_tools():
    with db() as c:
        rows = c.execute(
            "SELECT name, COALESCE(description,'') AS description, "
            "COALESCE(input_schema,'{}') AS input_schema, "
            "COALESCE(output_schema,'{}') AS output_schema, "
            "executor_kind, executor, COALESCE(tags,'') AS tags "
            "FROM tools ORDER BY name"
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "name": r["name"],
            "description": r["description"],
            "input_schema": json.loads(r["input_schema"]) if r["input_schema"] else {},
            "output_schema": json.loads(r["output_schema"]) if r["output_schema"] else {},
            "executor_kind": r["executor_kind"],
            "executor": r["executor"],
            "tags": r["tags"],
        })
    return out


@st.cache_data(ttl=5)
def load_workflows():
    with db() as c:
        rows = c.execute(
            "SELECT name, COALESCE(description,'') AS description, "
            "steps_json, COALESCE(use_count,0) AS use_count "
            "FROM workflows ORDER BY use_count DESC, name"
        ).fetchall()
    return [{
        "name": r["name"], "description": r["description"],
        "steps": json.loads(r["steps_json"]) if r["steps_json"] else [],
        "use_count": r["use_count"],
    } for r in rows]


@st.cache_data(ttl=5)
def load_projects():
    with db() as c:
        rows = c.execute(
            "SELECT name, COALESCE(path,'') AS path, created_at "
            "FROM projects ORDER BY id DESC LIMIT 30"
        ).fetchall()
    return [{"name": r[0], "path": r[1], "created_at": r[2]} for r in rows]


@st.cache_data(ttl=10)
def gpu_status():
    if not shutil.which("nvidia-smi"):
        return None
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        out = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                out.append({"name": parts[0], "util": parts[1],
                            "used": parts[2], "total": parts[3]})
        return out
    except Exception:
        return None


@st.cache_data(ttl=10)
def ollama_loaded():
    try:
        if requests is not None:
            r = requests.get(f"{OLLAMA_URL}/api/ps", timeout=3)
            return r.json().get("models", [])
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=3) as resp:
            return json.loads(resp.read()).get("models", [])
    except Exception:
        return []


# ---- asset routing -----------------------------------------------------

def asset_kind_for_path(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in (".mp4", ".webm", ".mov", ".mkv", ".avi"):
        return "video"
    if ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
        return "audio"
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        return "images"
    if ext in (".csv", ".jsonl", ".parquet", ".tsv"):
        return "datasets"
    if ext in (".safetensors", ".gguf", ".onnx", ".bin"):
        return "models"
    return "intermediate"


def list_assets(kind: str) -> list[Path]:
    d = ASSETS_DIR / kind
    if not d.exists():
        return []
    return sorted([p for p in d.iterdir() if p.is_file()])


def stash_upload(uploaded, kind: str | None = None) -> Path:
    """Persist a Streamlit-uploaded file into the right assets folder."""
    name = uploaded.name
    chosen = kind or asset_kind_for_path(Path(name))
    dest_dir = ASSETS_DIR / chosen
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if dest.exists():
        stem, suf = dest.stem, dest.suffix
        dest = dest_dir / f"{stem}_{int(time.time())}{suf}"
    dest.write_bytes(uploaded.getbuffer())
    return dest


# ---- chat backend ------------------------------------------------------

def detect_backend():
    if shutil.which("claude"):
        return ("claude", None)
    return ("ollama", CHAT_FALLBACK_MODEL)


def scope_system_prompt():
    s = st.session_state
    task = s.get("active_task")
    scope = s.get("current_scope") or str(CC_STUDIO_HOME)
    cur_file = s.get("current_file") or ""
    proj = s.get("active_project") or ""
    task_label = TASKS_BY_ID[task][2] if task else "(none)"
    return (
        "You are inside cc studio. User context:\n"
        f"- task:          {task_label}\n"
        f"- scope:         {scope}\n"
        f"- current_file:  {cur_file or '(none)'}\n"
        f"- project:       {proj or '(none)'}\n"
        "Assets live in cc-studio/assets/{video,audio,images,models,datasets,renders}.\n"
        "When the user says 'this' or 'here', interpret as current_file when set, "
        "else the scope dir. Be terse. If suggesting a multi-step plan, number it."
    )


def chat_with_claude(history, user_msg):
    parts = []
    for m in history:
        parts.append(f"[{m['role']}]\n{m['content']}")
    parts.append(f"[user]\n{user_msg}")
    parts.append("[assistant]\n")
    prompt = "\n\n".join(parts)
    try:
        r = subprocess.run(
            ["claude", "-p", "--append-system-prompt", scope_system_prompt(), prompt],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S,
        )
        if r.returncode != 0:
            return None, f"claude rc={r.returncode}: {r.stderr.strip()[:400]}"
        return r.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return None, f"claude timed out after {CLAUDE_TIMEOUT_S}s"
    except Exception as e:
        return None, f"claude error: {e}"


def chat_with_ollama(history, user_msg, model):
    messages = [{"role": "system", "content": scope_system_prompt()}]
    for m in history:
        if m["role"] in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_msg})
    payload = {
        "model": model, "messages": messages, "stream": False,
        "options": {"temperature": 0.2, "seed": 42},
        "keep_alive": "60s",
    }
    url = f"{OLLAMA_URL}/api/chat"
    try:
        if requests is not None:
            r = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT_S)
            data = r.json()
        else:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
        msg = (data.get("message") or {}).get("content", "")
        if not msg and data.get("error"):
            return None, f"ollama error: {data['error'][:400]}"
        return msg.strip(), None
    except Exception as e:
        return None, f"ollama error ({model}): {e}"


def handle_chat_turn(prompt: str):
    s = st.session_state
    history = list(s["chat_history"])
    s["chat_history"].append({"role": "user", "content": prompt})
    backend, model = (s.get("forced_backend") or detect_backend())
    if backend == "claude":
        reply, err = chat_with_claude(history, prompt)
    else:
        reply, err = chat_with_ollama(history, prompt, model)
        if err and ("404" in err or "not found" in err.lower()):
            reply, err = chat_with_ollama(history, prompt, CHAT_FALLBACK_MODEL_2)
    s["chat_history"].append({
        "role": "assistant",
        "content": (f"_(error: {err})_" if err else reply or ""),
    })


# ---- design tool dialog ------------------------------------------------

@st.dialog("🛠 Design Tool", width="large")
def design_tool_dialog():
    st.caption("Register a new tool — typed, deterministic capability.")
    name = st.text_input("Name (no spaces)", key="dt_name")
    desc = st.text_input("Description", key="dt_desc")
    kind = st.selectbox("Kind", ["bash", "python", "streamlit_fragment"], key="dt_kind")
    cols = st.columns(2)
    with cols[0]:
        inp = st.text_area("Input schema (JSON)", value='{}', height=120, key="dt_in")
    with cols[1]:
        outp = st.text_area("Output schema (JSON)", value='{}', height=120, key="dt_out")
    execu = st.text_area("Executor (bash template / module:func)", value="", height=100, key="dt_exec")
    tags = st.text_input("Tags (comma-separated)", key="dt_tags",
                         placeholder="audio,video,image,...")
    bcols = st.columns([1, 1, 4])
    with bcols[0]:
        if st.button("✓ Save", type="primary", use_container_width=True):
            if not name or not execu:
                st.error("name and executor required"); return
            try:
                json.loads(inp); json.loads(outp)
            except Exception as e:
                st.error(f"invalid JSON: {e}"); return
            with db() as c:
                c.execute(
                    "INSERT INTO tools(name, description, input_schema, output_schema, "
                    "executor_kind, executor, tags) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
                    "input_schema=excluded.input_schema, output_schema=excluded.output_schema, "
                    "executor_kind=excluded.executor_kind, executor=excluded.executor, tags=excluded.tags",
                    (name, desc, inp, outp, kind, execu, tags),
                )
            load_tools.clear()
            st.success(f"tool '{name}' saved")
            st.rerun()
    with bcols[1]:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


# ---- top global actions ------------------------------------------------

def render_top():
    s = st.session_state
    cols = st.columns([4, 1, 1, 1, 1])
    with cols[0]:
        st.markdown("### 🪞 cc studio")
    with cols[1]:
        if st.button("🏠", key="top_home", help="back to task picker", use_container_width=True):
            s["active_task"] = None
            s["selected_workflow"] = None
            st.rerun()
    with cols[2]:
        if st.button("🔄", key="top_refresh", help="refresh caches", use_container_width=True):
            for fn in (load_tools, load_workflows, load_projects, gpu_status, ollama_loaded):
                try: fn.clear()
                except Exception: pass
            st.rerun()
    with cols[3]:
        if st.button("🧹", key="top_clear", help="clear chat history", use_container_width=True):
            s["chat_history"] = []
            st.rerun()
    with cols[4]:
        if st.button("🛠", key="top_design", help="design tool", use_container_width=True):
            design_tool_dialog()


# ---- task picker (front door) ------------------------------------------

def render_task_picker():
    st.markdown("#### What do you want to do?")
    cols = st.columns(len(TASKS))
    for col, (tid, icon, label, _tags, _kind) in zip(cols, TASKS):
        with col:
            if st.button(f"{icon}\n{label}", key=f"tp_{tid}", use_container_width=True):
                st.session_state["active_task"] = tid
                st.rerun()


# ---- task panel (per-task UI) ------------------------------------------

def filter_tools_by_tags(tools, want_tags):
    if not want_tags:
        return tools
    out = []
    for t in tools:
        ttags = [s.strip().lower() for s in (t["tags"] or "").split(",") if s.strip()]
        for w in want_tags:
            if w.lower() in ttags:
                out.append(t); break
    return out


def render_asset_picker(kind: str):
    """Drop-in asset chooser for a single kind. Returns selected Path or None."""
    files = list_assets(kind)
    head = st.columns([4, 1])
    with head[0]:
        st.caption(f"📂 cc-studio/assets/**{kind}/**  ({len(files)} files)")
    with head[1]:
        upload = st.file_uploader(f"+ add {kind}", type=None,
                                  key=f"up_{kind}", label_visibility="collapsed")
    if upload:
        dest = stash_upload(upload, kind=kind)
        st.success(f"saved: {dest.name}")
        st.session_state["current_file"] = str(dest)
        st.rerun()
    if not files:
        st.caption(f"(no {kind} yet — upload one above)")
        return None
    options = ["(none)"] + [p.name for p in files]
    current = st.session_state.get(f"asset_{kind}_pick", "(none)")
    pick = st.selectbox("pick one", options, key=f"asset_{kind}_pick",
                        index=options.index(current) if current in options else 0,
                        label_visibility="collapsed")
    if pick != "(none)":
        chosen = next((p for p in files if p.name == pick), None)
        if chosen:
            st.session_state["current_file"] = str(chosen)
            st.session_state["current_scope"] = str(chosen.parent)
            return chosen
    return None


def render_tool_grid(tools, max_show=12):
    if not tools:
        st.caption("(no tools matched — use 🛠 to design one)")
        return
    st.caption(f"**Suggested tools** ({len(tools)})")
    cols = st.columns(3)
    for i, t in enumerate(tools[:max_show]):
        with cols[i % 3]:
            with st.container(border=True):
                st.markdown(f"**{t['name']}**")
                st.caption(t["description"] or "—")
                if st.button("▶ run", key=f"tg_run_{t['name']}", use_container_width=True):
                    st.session_state["selected_tool"] = t["name"]
                    st.rerun()


def render_task_panel(tools):
    s = st.session_state
    tid = s["active_task"]
    if tid not in TASKS_BY_ID:
        return
    _, icon, label, tags, kind = TASKS_BY_ID[tid]
    head = st.columns([8, 1])
    with head[0]:
        st.markdown(f"### {icon} {label}")
    with head[1]:
        if st.button("✕ close", key="task_close", use_container_width=True):
            s["active_task"] = None
            st.rerun()

    # Special handling per task
    if tid == "design_tool":
        st.caption("Click below to open the design dialog.")
        if st.button("🛠 Open Design Tool dialog", use_container_width=True):
            design_tool_dialog()
        return

    if tid == "agent_chat":
        st.caption("Free-form chat with the studio agent. Type in the input below.")
        return

    if tid == "custom":
        st.caption("Blank canvas — type any instruction in the chat below.")
        return

    # Asset picker for tasks with a kind
    if kind:
        st.markdown("**Input asset**")
        render_asset_picker(kind)
        st.markdown("---")

    # Suggested tools by tag match
    filtered = filter_tools_by_tags(tools, tags)
    render_tool_grid(filtered)


# ---- target cell (always visible) --------------------------------------

def render_target_cell():
    s = st.session_state
    file = s.get("current_file")
    scope = s.get("current_scope") or str(CC_STUDIO_HOME)
    proj = s.get("active_project", "")
    task = s.get("active_task")
    task_label = TASKS_BY_ID[task][2] if task else "(no task)"

    with st.container(border=True):
        cols = st.columns([5, 1, 1, 2])
        with cols[0]:
            if file:
                st.caption(f"📌 **file**: `{file}`")
                st.caption(f"🎯 scope: `{scope}`  ·  📦 task: {task_label}")
            else:
                st.caption(f"🎯 **scope**: `{scope}`  ·  📦 task: {task_label}")
        with cols[1]:
            if file:
                if st.button("✕", key="tc_clear_file", use_container_width=True,
                             help="clear file"):
                    s["current_file"] = None
                    st.rerun()
            else:
                if st.button("⌂", key="tc_reset", use_container_width=True,
                             help="reset scope to cc-studio"):
                    s["current_scope"] = str(CC_STUDIO_HOME)
                    st.rerun()
        with cols[2]:
            if st.button("📂", key="tc_browse", use_container_width=True,
                         help="open browse shelf"):
                s["active_shelf"] = "browse" if s.get("active_shelf") != "browse" else None
                st.rerun()
        with cols[3]:
            if proj:
                if st.button(f"➕ to «{proj}»", key="tc_attach", use_container_width=True):
                    item = f"target: {file or scope}"
                    with db() as c:
                        row = c.execute("SELECT id FROM projects WHERE name=?", (proj,)).fetchone()
                        if row:
                            c.execute("INSERT INTO todos(project_id, task) VALUES(?,?)", (row[0], item))
                    st.success(f"added '{item}'")
                    st.rerun()
            else:
                if st.button("✚ new project", key="tc_newproj", use_container_width=True):
                    new_name = Path(scope).name or "untitled"
                    s["active_project"] = new_name
                    with db() as c:
                        c.execute("INSERT OR IGNORE INTO projects(name, path) VALUES(?,?)",
                                  (new_name, scope))
                    load_projects.clear()
                    st.rerun()


# ---- shelves -----------------------------------------------------------

SHELF_ITEMS = [
    ("🤗", "hf",        "HF"),
    ("📂", "browse",    "Browse"),
    ("🔧", "tools",     "Tools"),
    ("⚙",  "workflows", "Workflows"),
    ("🧠", "models",    "Models"),
    ("📊", "datasets",  "Datasets"),
    ("🖥", "terminal",  "Terminal"),
]


def render_shelf_toggles():
    s = st.session_state
    cols = st.columns(len(SHELF_ITEMS))
    for col, (icon, key, label) in zip(cols, SHELF_ITEMS):
        with col:
            active = s.get("active_shelf") == key
            label_txt = f"{icon} {label}" + (" ✕" if active else "")
            if st.button(label_txt, key=f"sh_{key}", use_container_width=True,
                         type=("primary" if active else "secondary")):
                s["active_shelf"] = None if active else key
                st.rerun()


def render_shelf_input_form():
    s = st.session_state
    backend, model = (s.get("forced_backend") or detect_backend())
    ph = f"ask {backend}" + (f" ({model})" if model else "") + "…"
    with st.form(key="shelf_form", clear_on_submit=True, border=False):
        cols = st.columns([15, 1])
        with cols[0]:
            text = st.text_input("msg", placeholder=ph, label_visibility="collapsed",
                                 key="shelf_text")
        with cols[1]:
            send = st.form_submit_button("▶", use_container_width=True)
    if send and text.strip():
        handle_chat_turn(text.strip())
        st.rerun()


def render_shelf_content(key, tools, workflows):
    s = st.session_state
    if key == "hf":
        q = st.text_input("HF search", placeholder="lipsync, voice clone, sd-xl…",
                          key="hf_q", label_visibility="collapsed")
        if q:
            try:
                if requests:
                    res = requests.get(
                        f"https://huggingface.co/api/models?search={q}&limit=10&sort=downloads",
                        timeout=10,
                    ).json()
                else:
                    with urllib.request.urlopen(
                        f"https://huggingface.co/api/models?search={q}&limit=10",
                        timeout=10,
                    ) as r:
                        res = json.loads(r.read())
                for r in res[:8]:
                    with st.container(border=True):
                        c1, c2 = st.columns([4, 1])
                        with c1:
                            st.markdown(f"**{r['id']}**")
                            st.caption(f"{r.get('pipeline_tag','?')} · ⬇ {r.get('downloads',0):,}")
                        with c2:
                            st.link_button("Open ↗", f"https://huggingface.co/{r['id']}")
            except Exception as e:
                st.error(f"HF: {e}")
    elif key == "browse":
        st.caption(f"`{CC_STUDIO_HOME}`")
        def walk(p, depth=0):
            try: entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except Exception: return
            for e in entries:
                if e.name.startswith("."): continue
                indent = "  " * depth
                is_dir = e.is_dir()
                cols2 = st.columns([14, 2])
                selected = (s.get("current_file") == str(e)) or (
                    not s.get("current_file") and s.get("current_scope") == str(e))
                with cols2[0]:
                    if st.button(f"{indent}{'📁' if is_dir else '📄'} {e.name}",
                                 key=f"br_{e}", use_container_width=True,
                                 type=("primary" if selected else "secondary")):
                        if is_dir:
                            s["current_scope"] = str(e); s["current_file"] = None
                        else:
                            s["current_file"] = str(e); s["current_scope"] = str(e.parent)
                        st.rerun()
                with cols2[1]:
                    if is_dir:
                        if st.button("▾", key=f"brx_{e}", use_container_width=True):
                            s.setdefault("br_open", {})
                            s["br_open"][str(e)] = not s["br_open"].get(str(e), False)
                            st.rerun()
                if is_dir and s.get("br_open", {}).get(str(e)) and depth < 3:
                    walk(e, depth + 1)
        walk(CC_STUDIO_HOME)
    elif key == "tools":
        for t in tools:
            with st.container(border=True):
                cols2 = st.columns([3, 1])
                with cols2[0]:
                    st.markdown(f"**{t['name']}**  ·  `{t['executor_kind']}`")
                    st.caption(t["description"])
                with cols2[1]:
                    if st.button("inspect", key=f"sti_{t['name']}", use_container_width=True):
                        s[f"inspect_{t['name']}"] = not s.get(f"inspect_{t['name']}", False)
                if s.get(f"inspect_{t['name']}"):
                    inspect_cols = st.columns(2)
                    with inspect_cols[0]:
                        st.json(t.get("input_schema", {}))
                    with inspect_cols[1]:
                        st.json(t.get("output_schema", {}))
                    st.code(t.get("executor", ""), language="bash")
    elif key == "workflows":
        for wf in workflows:
            with st.container(border=True):
                st.markdown(f"**{wf['name']}** — {wf['description']}")
                st.caption(" → ".join(s2.get("tool", "?") for s2 in wf["steps"]))
                if st.button("open ▸", key=f"swf_{wf['name']}", use_container_width=True):
                    s["selected_workflow"] = wf["name"]
                    s["active_shelf"] = None
                    st.rerun()
    elif key == "models":
        for m in ollama_loaded():
            st.caption(f"🟢 {m.get('name','?')}  ·  {int(m.get('size_vram',0))//1048576} MB")
    elif key == "datasets":
        for kind in ASSET_KINDS:
            files = list_assets(kind)
            if files:
                st.markdown(f"**{kind}** ({len(files)})")
                for f in files[:10]:
                    st.caption(f"  📄 {f.name}")
    elif key == "terminal":
        s.setdefault("term_history", [])
        with st.form(key="term_form", clear_on_submit=True, border=False):
            cols2 = st.columns([15, 1])
            with cols2[0]:
                cmd = st.text_input("cmd", placeholder="cc tool list, ls -la, …",
                                    key="term_cmd", label_visibility="collapsed")
            with cols2[1]:
                run = st.form_submit_button("▶", use_container_width=True)
        if run and cmd.strip():
            try:
                r = subprocess.run(["bash", "-c", cmd], capture_output=True,
                                   text=True, timeout=30)
                out = (r.stdout + (("\n" + r.stderr) if r.stderr else "")).strip()
                rc = r.returncode
            except Exception as e:
                out = f"error: {e}"; rc = -1
            s["term_history"].append({"cmd": cmd, "output": out, "rc": rc})
            st.rerun()
        for h in reversed(s["term_history"][-10:]):
            with st.container(border=True):
                st.caption(f"{'🟢' if h['rc']==0 else '🔴'} `$ {h['cmd']}`  rc={h['rc']}")
                if h["output"]:
                    st.code(h["output"][:4000], language="text")


# ---- workflow renderer (when one is open) ------------------------------

def render_workflow_runner(wf, tools_by_name):
    s = st.session_state
    s.setdefault("vars", {})
    head = st.columns([6, 1])
    with head[0]:
        st.markdown(f"### ⚙ Workflow: `{wf['name']}`")
        st.caption(wf["description"])
    with head[1]:
        if st.button("✕ close", key="wfr_close", use_container_width=True):
            s["selected_workflow"] = None
            s["vars"] = {}
            st.rerun()
    for i, step in enumerate(wf["steps"]):
        tname = step.get("tool")
        tool = tools_by_name.get(tname)
        with st.expander(f"▸ step {i+1}: {tname}", expanded=(i == 0)):
            if not tool:
                st.error(f"tool '{tname}' missing"); continue
            st.caption(tool["description"])
            # binds resolved
            binds = step.get("binds", {})
            resolved = {k: (s["vars"].get(v[1:], "") if isinstance(v, str) and v.startswith("$") else v)
                        for k, v in binds.items()}
            st.json(resolved)
            if st.button(f"▶ run step {i+1}", key=f"wfr_run_{i}"):
                if tool["executor_kind"] != "bash":
                    st.warning("only bash kind runnable from studio for now"); continue
                templ = tool["executor"]
                for k, v in resolved.items():
                    templ = templ.replace("${" + k + "}", str(v)).replace("$" + k, str(v))
                try:
                    r = subprocess.run(["bash", "-c", templ], capture_output=True,
                                       text=True, timeout=300)
                    out = r.stdout
                    s["vars"][step.get("out", f"step_{i}_out")] = out.strip()
                    st.code(out[:2000])
                    if r.stderr:
                        st.caption("stderr:"); st.code(r.stderr[:1000])
                except Exception as e:
                    st.error(str(e))


# ---- main --------------------------------------------------------------

def main():
    st.set_page_config(page_title="cc studio", layout="wide", page_icon="🪞")

    s = st.session_state
    s.setdefault("active_task", None)
    s.setdefault("active_shelf", None)
    s.setdefault("active_project", "")
    s.setdefault("selected_workflow", None)
    s.setdefault("chat_history", [])
    s.setdefault("current_scope", str(CC_STUDIO_HOME))
    s.setdefault("current_file", None)

    tools = load_tools()
    tools_by_name = {t["name"]: t for t in tools}
    workflows = load_workflows()

    # ===== TOP: global actions =====
    render_top()
    st.markdown("---")

    shelf_open = bool(s.get("active_shelf"))

    # ===== SHELF (above the chat history when open) =====
    if shelf_open:
        with st.container(border=True):
            head = st.columns([6, 1])
            with head[0]:
                st.caption(f"📦 **{s['active_shelf']}** shelf")
            with head[1]:
                if st.button("✕ close", key="shelf_close", use_container_width=True):
                    s["active_shelf"] = None
                    st.rerun()
            render_shelf_input_form()
            st.markdown("---")
            render_shelf_content(s["active_shelf"], tools, workflows)
        st.markdown("---")

    # ===== MIDDLE: task picker OR workflow runner OR task panel =====
    if s["selected_workflow"]:
        wf = next((w for w in workflows if w["name"] == s["selected_workflow"]), None)
        if wf:
            render_workflow_runner(wf, tools_by_name)
        else:
            s["selected_workflow"] = None
    elif s["active_task"]:
        render_task_panel(tools)
    else:
        render_task_picker()

    # Chat history (appears under task panel / workflow runner)
    if s["chat_history"]:
        st.markdown("---")
        for m in s["chat_history"]:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

    # ===== BOTTOM (always visible): target · toggles · chat input =====
    st.markdown("---")
    render_target_cell()
    render_shelf_toggles()

    backend, model = (s.get("forced_backend") or detect_backend())
    ph = f"ask {backend}" + (f" ({model})" if model else "") + "…"
    prompt = st.chat_input(ph, key="chat_input")
    if prompt:
        handle_chat_turn(prompt)
        st.rerun()


if __name__ == "__main__":
    if not CC_DB.exists():
        print(f"cc db not found at {CC_DB}", file=sys.stderr)
        sys.exit(1)
    main()
