#!/usr/bin/env python3
"""cc tui — curses dashboard for cc state.

Tabs: Chats | Agents | Swarms | Phases | Todos
Nav:  j/k or arrows; 1-5 jump tabs; Enter views; a = assign to project;
      r = refresh; / = search; q = quit.

Colors:
  ~claude   cyan       claude sessions
  ~ollama   yellow     local-model invocations
  ~project  green      scoped to a real project
  ~orphan   red        unlabeled / not assigned
"""
import curses
import os
import sqlite3
import sys
from pathlib import Path

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
CC_GLOBAL_DB = Path(os.environ.get("CC_GLOBAL_DB", str(CC_HOME / "cc.db")))
CC_LOCAL_DB = os.environ.get("CC_SCOPE_LOCAL_DB", "") or None
PROJECT = os.environ.get("CC_SCOPE_GLOBAL_PROJECT") or "(none)"
LOCAL_PROJECT = os.environ.get("CC_SCOPE_LOCAL_PROJECT") or "(unscoped)"
CWD = os.environ.get("CC_SCOPE_CWD", os.getcwd())

C_CLAUDE = 1
C_OLLAMA = 2
C_PROJECT = 3
C_ORPHAN = 4
C_HEADER = 5
C_HIGHLIGHT = 6
C_DIM = 7

TABS = ["Chats", "Agents", "Swarms", "Phases", "Todos"]


def gdb():
    c = sqlite3.connect(str(CC_GLOBAL_DB))
    c.row_factory = sqlite3.Row
    return c


def ldb():
    if not CC_LOCAL_DB or not Path(CC_LOCAL_DB).exists():
        return None
    c = sqlite3.connect(CC_LOCAL_DB)
    c.row_factory = sqlite3.Row
    return c


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_CLAUDE, curses.COLOR_CYAN, -1)
    curses.init_pair(C_OLLAMA, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_PROJECT, curses.COLOR_GREEN, -1)
    curses.init_pair(C_ORPHAN, curses.COLOR_RED, -1)
    curses.init_pair(C_HEADER, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(C_HIGHLIGHT, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(C_DIM, curses.COLOR_WHITE, -1)


# ---- loaders ------------------------------------------------------------

def load_chats():
    c = gdb()
    rows = c.execute(
        """
        SELECT chats.id AS id, COALESCE(projects.name,'(orphan)') AS proj,
               session_id, source, COALESCE(started_at,'') AS started,
               COALESCE(message_count,0) AS msgs, COALESCE(summary,'') AS summary
        FROM chats LEFT JOIN projects ON projects.id = chats.project_id
        ORDER BY chats.id DESC LIMIT 100
        """
    ).fetchall()
    return [dict(r) for r in rows]


def load_agents():
    c = gdb()
    rows = c.execute(
        "SELECT name, model, COALESCE(description,'') AS description FROM agent_defs ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def load_swarms():
    c = gdb()
    rows = c.execute(
        "SELECT name, COALESCE(description,'') AS description, "
        "COALESCE(loop_until,'') AS loop_until, max_iters FROM swarm_defs ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def load_phases():
    c = gdb()
    rows = c.execute(
        """
        SELECT p.id AS id, p.name AS name, p.status AS status,
               COALESCE(p.started_at,'') AS started, COALESCE(p.summary,'') AS summary,
               COALESCE(pr.name,'(orphan)') AS proj
        FROM phases p LEFT JOIN projects pr ON pr.id = p.project_id
        ORDER BY p.id DESC LIMIT 50
        """
    ).fetchall()
    return [dict(r) for r in rows]


def load_todos():
    c = gdb()
    rows = c.execute(
        """
        SELECT t.id AS id, t.task AS task, t.status AS status,
               COALESCE(p.name,'(orphan)') AS proj
        FROM todos t LEFT JOIN projects p ON p.id = t.project_id
        ORDER BY t.id DESC LIMIT 100
        """
    ).fetchall()
    return [dict(r) for r in rows]


LOADERS = [load_chats, load_agents, load_swarms, load_phases, load_todos]


# ---- rendering ----------------------------------------------------------

def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h:
        return
    max_len = max(0, w - x - 1)
    win.addstr(y, x, text[:max_len], attr)


def render_status(stdscr):
    h, w = stdscr.getmaxyx()
    status = (
        f" cc tui │ global: {PROJECT} │ local: {LOCAL_PROJECT} │ cwd: {CWD} "
    )
    safe_addstr(stdscr, 0, 0, status.ljust(w - 1), curses.color_pair(C_HEADER))


def render_tabs(stdscr, current_tab):
    h, w = stdscr.getmaxyx()
    x = 1
    for i, name in enumerate(TABS):
        label = f" [{i+1}] {name} "
        if i == current_tab:
            safe_addstr(stdscr, 1, x, label, curses.color_pair(C_HIGHLIGHT))
        else:
            safe_addstr(stdscr, 1, x, label, curses.A_DIM)
        x += len(label) + 1


def tag_attr(tag):
    return {
        "~claude": curses.color_pair(C_CLAUDE),
        "~ollama": curses.color_pair(C_OLLAMA),
        "~tiny":   curses.color_pair(C_OLLAMA),
        "~project": curses.color_pair(C_PROJECT),
        "~orphan": curses.color_pair(C_ORPHAN),
    }.get(tag, 0)


def fmt_row(idx, tab, item):
    """Returns list of (text, attr) segments for one row."""
    if tab == 0:  # Chats
        proj = item["proj"]
        proj_tag = "~orphan" if proj == "(orphan)" else "~project"
        return [
            (f"#{item['id']:>4}  ", 0),
            (f"{item['session_id'][:8]}  ", curses.A_BOLD),
            ("~claude  ", curses.color_pair(C_CLAUDE)),
            (f"{proj_tag:<8}  ", tag_attr(proj_tag)),
            (f"[{proj}]  ", curses.color_pair(C_PROJECT if proj_tag == "~project" else C_ORPHAN)),
            (f"msgs={item['msgs']:<4}  ", 0),
            (f"{item['started'][:19]}  ", curses.A_DIM),
            (item.get("summary", "")[:80], 0),
        ]
    if tab == 1:  # Agents
        return [
            (f"{item['name']:<26}  ", curses.A_BOLD),
            ("~ollama  ", curses.color_pair(C_OLLAMA)),
            (f"[{item['model']}]  ", curses.A_DIM),
            (item["description"][:80], 0),
        ]
    if tab == 2:  # Swarms
        loop = item.get("loop_until") or ""
        loop_part = f"loop_until='{loop}'  " if loop else ""
        return [
            (f"{item['name']:<26}  ", curses.A_BOLD),
            ("~ollama  ", curses.color_pair(C_OLLAMA)),
            (f"max={item['max_iters']:<3}  ", curses.A_DIM),
            (loop_part, curses.color_pair(C_OLLAMA)),
            (item["description"][:60], 0),
        ]
    if tab == 3:  # Phases
        proj = item["proj"]
        proj_tag = "~orphan" if proj == "(orphan)" else "~project"
        status_color = C_PROJECT if item["status"] == "active" else C_DIM
        return [
            (f"#{item['id']:>3}  ", 0),
            (f"[{item['status']:<7}]  ", curses.color_pair(status_color)),
            (f"{proj_tag:<8}  ", tag_attr(proj_tag)),
            (f"[{proj}]  ", curses.color_pair(C_PROJECT if proj_tag == "~project" else C_ORPHAN)),
            (f"{item['name']:<28}  ", curses.A_BOLD),
            (item["started"][:19] + "  ", curses.A_DIM),
            (item.get("summary", "")[:50], 0),
        ]
    if tab == 4:  # Todos
        proj = item["proj"]
        proj_tag = "~orphan" if proj == "(orphan)" else "~project"
        mark = "[x]" if item["status"] == "done" else "[ ]"
        return [
            (f"{mark}  ", 0),
            (f"#{item['id']:>4}  ", 0),
            (f"{proj_tag:<8}  ", tag_attr(proj_tag)),
            (f"[{proj}]  ", curses.color_pair(C_PROJECT if proj_tag == "~project" else C_ORPHAN)),
            (item["task"][:90], 0),
        ]
    return [(str(item), 0)]


def render_list(stdscr, tab, items, selected, top):
    h, w = stdscr.getmaxyx()
    visible = h - 5
    if selected < top:
        top = selected
    if selected >= top + visible:
        top = selected - visible + 1

    if not items:
        safe_addstr(stdscr, 3, 2, "(no items in this tab)", curses.A_DIM)
        return top

    for i in range(visible):
        idx = top + i
        if idx >= len(items):
            break
        y = 3 + i
        segs = fmt_row(idx, tab, items[idx])
        x = 0
        if idx == selected:
            # highlight whole row first
            safe_addstr(stdscr, y, 0, " " * (w - 1), curses.color_pair(C_HIGHLIGHT))
        for text, attr in segs:
            if idx == selected:
                attr = (attr & ~curses.A_DIM) | curses.color_pair(C_HIGHLIGHT)
            safe_addstr(stdscr, y, x, text, attr)
            x += len(text)
    return top


def render_help(stdscr):
    h, w = stdscr.getmaxyx()
    help_line = " [↑↓/jk] nav  [Enter] view  [a] assign to project  [r] refresh  [1-5] tab  [q] quit "
    safe_addstr(stdscr, h - 1, 0, help_line.ljust(w - 1), curses.color_pair(C_HEADER))


# ---- actions ------------------------------------------------------------

def detail_view(stdscr, tab, item):
    """Show details for a row. Pops up a full-screen overlay until any key."""
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    safe_addstr(stdscr, 0, 0, " DETAIL ".ljust(w - 1), curses.color_pair(C_HEADER))
    y = 2

    if tab == 0:  # Chat
        c = gdb()
        row = c.execute(
            "SELECT transcript_path, session_id FROM chats WHERE id=?", (item["id"],)
        ).fetchone()
        if row:
            path = row["transcript_path"]
            safe_addstr(stdscr, y, 0, f"transcript: {path}"); y += 2
            if path and Path(path).exists():
                try:
                    text = Path(path).read_text(errors="replace")
                    lines = text.splitlines()[:h - y - 3]
                    for line in lines:
                        if y >= h - 2:
                            break
                        safe_addstr(stdscr, y, 0, line)
                        y += 1
                except Exception as e:
                    safe_addstr(stdscr, y, 0, f"(error reading: {e})")
            else:
                safe_addstr(stdscr, y, 0, "(transcript file missing)")
    elif tab == 1:  # Agent
        c = gdb()
        row = c.execute(
            "SELECT name, model, prompt_template, COALESCE(description,'') AS d "
            "FROM agent_defs WHERE name=?",
            (item["name"],),
        ).fetchone()
        if row:
            safe_addstr(stdscr, y, 0, f"agent: {row['name']}", curses.A_BOLD); y += 1
            safe_addstr(stdscr, y, 0, f"model: {row['model']}"); y += 1
            safe_addstr(stdscr, y, 0, f"description: {row['d']}"); y += 2
            safe_addstr(stdscr, y, 0, "--- template ---", curses.A_DIM); y += 1
            for line in (row["prompt_template"] or "").splitlines():
                if y >= h - 2:
                    break
                safe_addstr(stdscr, y, 0, line)
                y += 1
    elif tab == 2:  # Swarm
        c = gdb()
        row = c.execute(
            "SELECT name, description, steps_json, COALESCE(loop_until,'') AS lu, max_iters "
            "FROM swarm_defs WHERE name=?",
            (item["name"],),
        ).fetchone()
        if row:
            safe_addstr(stdscr, y, 0, f"swarm: {row['name']}", curses.A_BOLD); y += 1
            safe_addstr(stdscr, y, 0, f"description: {row['description'] or ''}"); y += 1
            safe_addstr(stdscr, y, 0, f"loop_until:  {row['lu']}"); y += 1
            safe_addstr(stdscr, y, 0, f"max_iters:   {row['max_iters']}"); y += 2
            for line in (row["steps_json"] or "").splitlines():
                if y >= h - 2:
                    break
                safe_addstr(stdscr, y, 0, line)
                y += 1
    elif tab == 3:  # Phase
        c = gdb()
        safe_addstr(stdscr, y, 0, f"phase #{item['id']}: {item['name']}", curses.A_BOLD); y += 1
        safe_addstr(stdscr, y, 0, f"status:  {item['status']}"); y += 1
        safe_addstr(stdscr, y, 0, f"project: {item['proj']}"); y += 1
        safe_addstr(stdscr, y, 0, f"summary: {item.get('summary','')}"); y += 2
        for r in c.execute(
            "SELECT step_idx, model, response, done_seen FROM phase_steps "
            "WHERE phase_id=? ORDER BY step_idx",
            (item["id"],),
        ):
            if y >= h - 2:
                break
            mark = "✓" if r["done_seen"] else "⚠"
            safe_addstr(stdscr, y, 0, f"  step {r['step_idx']} [{r['model']}] {mark}", curses.A_DIM)
            y += 1
            for line in (r["response"] or "").splitlines()[:4]:
                if y >= h - 2:
                    break
                safe_addstr(stdscr, y, 2, line[:w - 3])
                y += 1
    elif tab == 4:  # Todo
        safe_addstr(stdscr, y, 0, f"todo #{item['id']}: {item['task']}", curses.A_BOLD); y += 1
        safe_addstr(stdscr, y, 0, f"status:  {item['status']}"); y += 1
        safe_addstr(stdscr, y, 0, f"project: {item['proj']}"); y += 1

    safe_addstr(stdscr, h - 1, 0, " press any key to return ".ljust(w - 1), curses.color_pair(C_HEADER))
    stdscr.refresh()
    stdscr.getch()


def project_picker(stdscr):
    """Modal: list projects, return chosen name or None on escape."""
    c = gdb()
    projs = [r["name"] for r in c.execute("SELECT name FROM projects ORDER BY name")]
    h, w = stdscr.getmaxyx()
    sel = 0
    while True:
        stdscr.clear()
        safe_addstr(stdscr, 0, 0, " ASSIGN TO PROJECT — select with Enter, Esc to cancel ".ljust(w - 1),
                    curses.color_pair(C_HEADER))
        if not projs:
            safe_addstr(stdscr, 2, 2, "(no projects defined — run `cc -setup` or `cc -set-project <name>` first)",
                        curses.color_pair(C_ORPHAN))
        for i, p in enumerate(projs[: h - 4]):
            attr = curses.color_pair(C_HIGHLIGHT) if i == sel else 0
            if i == sel:
                safe_addstr(stdscr, 2 + i, 0, " " * (w - 1), attr)
            safe_addstr(stdscr, 2 + i, 2, p, attr)
        stdscr.refresh()
        k = stdscr.getch()
        if k in (27, ord("q")):
            return None
        if k in (curses.KEY_UP, ord("k")):
            sel = max(0, sel - 1)
        elif k in (curses.KEY_DOWN, ord("j")):
            sel = min(len(projs) - 1, sel + 1)
        elif k in (10, 13):
            return projs[sel] if projs else None


def assign_to_project(stdscr, tab, item):
    """Reassign chats/phases/todos to a selected project."""
    if tab not in (0, 3, 4):
        return  # agents/swarms don't have project_id
    target = project_picker(stdscr)
    if not target:
        return
    c = gdb()
    pid = c.execute("SELECT id FROM projects WHERE name=?", (target,)).fetchone()
    if not pid:
        return
    pid = pid["id"]
    table = {0: "chats", 3: "phases", 4: "todos"}[tab]
    c.execute(f"UPDATE {table} SET project_id=? WHERE id=?", (pid, item["id"]))
    c.commit()


# ---- main loop ----------------------------------------------------------

def main(stdscr):
    curses.curs_set(0)
    init_colors()

    current_tab = 0
    items = LOADERS[current_tab]()
    selected = 0
    top = 0

    while True:
        stdscr.erase()
        render_status(stdscr)
        render_tabs(stdscr, current_tab)
        top = render_list(stdscr, current_tab, items, selected, top)
        render_help(stdscr)
        stdscr.refresh()

        k = stdscr.getch()
        if k in (ord("q"), 27):
            return
        elif k in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif k in (curses.KEY_DOWN, ord("j")):
            selected = min(max(0, len(items) - 1), selected + 1)
        elif k in (curses.KEY_NPAGE,):
            selected = min(max(0, len(items) - 1), selected + 10)
        elif k in (curses.KEY_PPAGE,):
            selected = max(0, selected - 10)
        elif ord("1") <= k <= ord("5"):
            current_tab = k - ord("1")
            items = LOADERS[current_tab]()
            selected = 0
            top = 0
        elif k in (10, 13):  # Enter
            if items:
                detail_view(stdscr, current_tab, items[selected])
        elif k == ord("a"):
            if items:
                assign_to_project(stdscr, current_tab, items[selected])
                items = LOADERS[current_tab]()
        elif k == ord("r"):
            items = LOADERS[current_tab]()


if __name__ == "__main__":
    if not CC_GLOBAL_DB.exists():
        print(f"cc db not found at {CC_GLOBAL_DB}", file=sys.stderr)
        sys.exit(1)
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
