#!/usr/bin/env python3
"""cc database helper — sqlite-backed CLI for projects/todos/scripts/log/queue.

Tables intentionally split so a stuck `current_task` or queued op can be
edited without colliding with the static todo list.

Usage:
  db.py init
  db.py set-project NAME
  db.py active                              # prints "name" or "" (also project_id\tname to stderr? no — keep stdout clean)
  db.py list-projects
  db.py add-todo PROJECT TASK
  db.py list-todos [PROJECT]
  db.py done TODO_ID
  db.py edit-todo TODO_ID NEW_TEXT
  db.py add-script PROJECT NAME PATH [DESCRIPTION]
  db.py list-scripts [PROJECT]
  db.py log-action PROJECT CWD ACTION SUMMARY
  db.py show-log [-n N]
  db.py queue-add PROJECT COMMAND
  db.py queue-list
  db.py queue-pop ID                        # returns command for ID, marks running
  db.py queue-done ID
  db.py current-set PROJECT TODO_ID
  db.py current-show
  db.py current-clear
"""
import os
import sqlite3
import sys
from pathlib import Path

DB = Path(os.environ.get("CC_DB", str(Path.home() / ".cc" / "cc.db")))


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=30.0, isolation_level=None)
    c.execute("PRAGMA foreign_keys = ON;")
    c.execute("PRAGMA journal_mode = WAL;")
    c.execute("PRAGMA synchronous = NORMAL;")
    c.execute("PRAGMA busy_timeout = 30000;")
    return c


def init() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS projects(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE NOT NULL,
          created_at TEXT DEFAULT (datetime('now')),
          active INTEGER DEFAULT 0,
          path TEXT
        );
        CREATE TABLE IF NOT EXISTS todos(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER REFERENCES projects(id),
          task TEXT NOT NULL,
          status TEXT DEFAULT 'pending',
          created_at TEXT DEFAULT (datetime('now')),
          completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS bash_scripts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER REFERENCES projects(id),
          name TEXT NOT NULL,
          path TEXT NOT NULL,
          description TEXT,
          created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS directory_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER REFERENCES projects(id),
          cwd TEXT NOT NULL,
          action TEXT NOT NULL,
          change_summary TEXT,
          created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS queue(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER REFERENCES projects(id),
          command TEXT NOT NULL,
          status TEXT DEFAULT 'queued',
          created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS current_task(
          id INTEGER PRIMARY KEY CHECK (id = 1),
          project_id INTEGER REFERENCES projects(id),
          todo_id INTEGER REFERENCES todos(id),
          started_at TEXT
        );
        CREATE TABLE IF NOT EXISTS meta(
          key TEXT PRIMARY KEY,
          value TEXT
        );
        CREATE TABLE IF NOT EXISTS entrypoints(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          path TEXT NOT NULL,
          kind TEXT NOT NULL,
          discovered_at TEXT DEFAULT (datetime('now')),
          last_run_at TEXT,
          last_rc INTEGER
        );
        CREATE TABLE IF NOT EXISTS runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL,
          command TEXT NOT NULL,
          rc INTEGER,
          stdout_tail TEXT,
          stderr_tail TEXT,
          started_at TEXT DEFAULT (datetime('now')),
          finished_at TEXT,
          agent_uuid TEXT
        );
        CREATE TABLE IF NOT EXISTS agents(
          uuid TEXT PRIMARY KEY,
          pid INTEGER,
          cwd TEXT,
          action TEXT,
          started_at TEXT DEFAULT (datetime('now')),
          finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tools(
          name TEXT PRIMARY KEY,
          description TEXT,
          input_schema TEXT,
          output_schema TEXT,
          executor_kind TEXT,
          executor TEXT,
          tags TEXT,
          created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS workflows(
          name TEXT PRIMARY KEY,
          description TEXT,
          steps_json TEXT NOT NULL,
          created_at TEXT DEFAULT (datetime('now')),
          last_used_at TEXT,
          use_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS workflow_runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          workflow_name TEXT NOT NULL,
          status TEXT DEFAULT 'active',
          vars_json TEXT,
          started_at TEXT DEFAULT (datetime('now')),
          ended_at TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_defs(
          name TEXT PRIMARY KEY,
          model TEXT,
          prompt_template TEXT NOT NULL,
          description TEXT,
          created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS swarm_defs(
          name TEXT PRIMARY KEY,
          description TEXT,
          steps_json TEXT NOT NULL,
          loop_until TEXT,
          max_iters INTEGER DEFAULT 10,
          created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS swarm_runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          swarm_name TEXT NOT NULL,
          status TEXT DEFAULT 'active',
          vars_json TEXT,
          started_at TEXT DEFAULT (datetime('now')),
          ended_at TEXT,
          iterations INTEGER DEFAULT 0,
          agent_uuid TEXT
        );
        CREATE TABLE IF NOT EXISTS swarm_run_steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          swarm_run_id INTEGER REFERENCES swarm_runs(id),
          iteration INTEGER,
          step_idx INTEGER,
          agent_name TEXT,
          inputs_json TEXT,
          output TEXT,
          done_seen INTEGER,
          started_at TEXT DEFAULT (datetime('now')),
          finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS phases(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER REFERENCES projects(id),
          name TEXT NOT NULL,
          status TEXT DEFAULT 'active',
          started_at TEXT DEFAULT (datetime('now')),
          ended_at TEXT,
          summary TEXT
        );
        CREATE TABLE IF NOT EXISTS phase_steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          phase_id INTEGER REFERENCES phases(id),
          step_idx INTEGER,
          model TEXT,
          prompt TEXT,
          response TEXT,
          done_seen INTEGER,
          started_at TEXT DEFAULT (datetime('now')),
          finished_at TEXT,
          agent_uuid TEXT
        );
        CREATE TABLE IF NOT EXISTS chats(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER REFERENCES projects(id),
          todo_id INTEGER,
          scope_cwd TEXT,
          session_id TEXT,
          source TEXT,
          agent_uuid TEXT,
          started_at TEXT,
          finished_at TEXT,
          message_count INTEGER,
          transcript_path TEXT,
          git_branch TEXT,
          forked_from TEXT,
          summary TEXT,
          content_hash TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS chain_runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          spec TEXT NOT NULL,
          started_at TEXT DEFAULT (datetime('now')),
          ended_at TEXT,
          status TEXT DEFAULT 'active',
          agent_uuid TEXT
        );
        CREATE TABLE IF NOT EXISTS chain_run_steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chain_run_id INTEGER REFERENCES chain_runs(id),
          step_idx INTEGER NOT NULL,
          op TEXT,
          isolated INTEGER DEFAULT 0,
          context_in TEXT,
          prompt TEXT,
          output TEXT,
          ms_elapsed INTEGER,
          from_cache INTEGER DEFAULT 0,
          started_at TEXT DEFAULT (datetime('now')),
          finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS capability_cards(
          opcode TEXT PRIMARY KEY,
          drafted_by TEXT,
          drafted_at TEXT DEFAULT (datetime('now')),
          card_json TEXT NOT NULL,
          source TEXT
        );
        CREATE TABLE IF NOT EXISTS gui_cards(
          opcode TEXT PRIMARY KEY,
          drafted_by TEXT,
          drafted_at TEXT DEFAULT (datetime('now')),
          card_json TEXT NOT NULL,
          source TEXT
        );
        CREATE TABLE IF NOT EXISTS workflow_templates(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          primary_opcode TEXT,
          description TEXT NOT NULL,
          tags TEXT,
          template_json TEXT NOT NULL,
          preconditions_json TEXT,
          fallbacks_json TEXT,
          authored_by TEXT NOT NULL,
          author_prompt_hash TEXT,
          created_at TEXT DEFAULT (datetime('now')),
          use_count INTEGER DEFAULT 0,
          last_used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS workflow_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          template_name TEXT,
          user_request TEXT NOT NULL,
          current_step INTEGER DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'planning',
          context_json TEXT,
          started_at TEXT DEFAULT (datetime('now')),
          ended_at TEXT,
          agent_uuid TEXT
        );
        CREATE TABLE IF NOT EXISTS workflow_job_steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id INTEGER REFERENCES workflow_jobs(id),
          step_idx INTEGER,
          opcode TEXT NOT NULL,
          purpose TEXT,
          chosen_model TEXT,
          inputs_json TEXT,
          output TEXT,
          human_checkpoint_type TEXT,
          human_decision TEXT,
          human_notes TEXT,
          started_at TEXT DEFAULT (datetime('now')),
          finished_at TEXT,
          ms_elapsed INTEGER
        );
        -- Hash-addressed DAG cache. Every opcode, every widget instance,
        -- every chain gets a stable sha256-based node_id. Async builders
        -- mark nodes stale; rebuilders refresh them. Lookups are O(1).
        CREATE TABLE IF NOT EXISTS dag_nodes(
          node_id TEXT PRIMARY KEY,
          node_kind TEXT NOT NULL,        -- opcode | widget | state | chain | transition
          name TEXT,
          payload_json TEXT NOT NULL,
          mui_component TEXT,             -- Material UI component name
          parent_node TEXT,               -- parent in the GUI tree
          created_at TEXT DEFAULT (datetime('now')),
          updated_at TEXT DEFAULT (datetime('now')),
          stale INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_dag_nodes_kind ON dag_nodes(node_kind);
        CREATE INDEX IF NOT EXISTS idx_dag_nodes_parent ON dag_nodes(parent_node);
        CREATE TABLE IF NOT EXISTS dag_edges(
          edge_id TEXT PRIMARY KEY,
          src_node TEXT NOT NULL,
          dst_node TEXT NOT NULL,
          edge_kind TEXT NOT NULL,        -- pipe | parallel | sequential | hitl | renders | input | output | succession | succession_ranked
          weight REAL DEFAULT 1.0,
          payload_json TEXT,
          created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_dag_edges_src ON dag_edges(src_node);
        CREATE INDEX IF NOT EXISTS idx_dag_edges_dst ON dag_edges(dst_node);
        CREATE INDEX IF NOT EXISTS idx_dag_edges_kind ON dag_edges(edge_kind);
        CREATE TABLE IF NOT EXISTS dag_chains(
          chain_id TEXT PRIMARY KEY,      -- sha256 of canonical "opcode1→opcode2→…"
          src_opcode TEXT NOT NULL,
          dst_opcode TEXT NOT NULL,
          chain_json TEXT NOT NULL,
          score REAL,
          intent_tags TEXT,
          gui_dag_root TEXT,              -- pointer to entry dag_node
          created_at TEXT DEFAULT (datetime('now')),
          updated_at TEXT DEFAULT (datetime('now')),
          stale INTEGER DEFAULT 0,
          hit_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_dag_chains_src ON dag_chains(src_opcode);
        CREATE INDEX IF NOT EXISTS idx_dag_chains_dst ON dag_chains(dst_opcode);
        CREATE INDEX IF NOT EXISTS idx_dag_chains_stale ON dag_chains(stale);
        CREATE TABLE IF NOT EXISTS dag_build_queue(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_kind TEXT NOT NULL,        -- rebuild_chain | rebuild_node | rebuild_successors | mark_stale
          target_id TEXT NOT NULL,
          priority INTEGER DEFAULT 0,
          status TEXT DEFAULT 'pending',  -- pending | running | done | failed
          enqueued_at TEXT DEFAULT (datetime('now')),
          started_at TEXT,
          finished_at TEXT,
          ms_elapsed INTEGER,
          error_text TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dag_queue_status ON dag_build_queue(status, priority DESC);
        COMMIT;
        """)
        # Backfill column if pre-existing db lacks projects.path
        cols = [r[1] for r in c.execute("PRAGMA table_info(projects);")]
        if "path" not in cols:
            c.execute("ALTER TABLE projects ADD COLUMN path TEXT;")


def get_or_create_project(c: sqlite3.Connection, name: str) -> int:
    row = c.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    cur = c.execute("INSERT INTO projects(name) VALUES(?)", (name,))
    return cur.lastrowid


def set_project(name: str) -> None:
    with conn() as c:
        c.execute("UPDATE projects SET active=0;")
        pid = get_or_create_project(c, name)
        c.execute("UPDATE projects SET active=1 WHERE id=?", (pid,))


def active() -> None:
    with conn() as c:
        row = c.execute("SELECT name FROM projects WHERE active=1 LIMIT 1;").fetchone()
        print(row[0] if row else "")


def list_projects() -> None:
    with conn() as c:
        for pid, name, active_flag, created in c.execute(
            "SELECT id,name,active,created_at FROM projects ORDER BY id"
        ):
            mark = "*" if active_flag else " "
            print(f"{mark} {pid:>3}  {name}  ({created})")


def _project_id(c: sqlite3.Connection, name: str | None) -> int | None:
    if name:
        row = c.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
        return row[0] if row else None
    row = c.execute("SELECT id FROM projects WHERE active=1 LIMIT 1;").fetchone()
    return row[0] if row else None


def add_todo(project: str, task: str) -> None:
    with conn() as c:
        pid = get_or_create_project(c, project)
        cur = c.execute("INSERT INTO todos(project_id, task) VALUES(?,?)", (pid, task))
        print(cur.lastrowid)


def list_todos(project: str | None) -> None:
    with conn() as c:
        pid = _project_id(c, project)
        if pid is None:
            return
        for tid, task, status, created in c.execute(
            "SELECT id,task,status,created_at FROM todos WHERE project_id=? ORDER BY id",
            (pid,),
        ):
            mark = {"pending": "[ ]", "done": "[x]"}.get(status, f"[{status}]")
            print(f"{mark} {tid:>4}  {task}  ({created})")


def done_todo(todo_id: int) -> None:
    with conn() as c:
        c.execute(
            "UPDATE todos SET status='done', completed_at=datetime('now') WHERE id=?",
            (todo_id,),
        )


def edit_todo(todo_id: int, new_text: str) -> None:
    with conn() as c:
        c.execute("UPDATE todos SET task=? WHERE id=?", (new_text, todo_id))


def add_script(project: str, name: str, path: str, description: str = "") -> None:
    with conn() as c:
        pid = get_or_create_project(c, project)
        c.execute(
            "INSERT INTO bash_scripts(project_id, name, path, description) VALUES(?,?,?,?)",
            (pid, name, path, description),
        )


def list_scripts(project: str | None) -> None:
    with conn() as c:
        pid = _project_id(c, project)
        if pid is None:
            return
        for sid, name, path, desc in c.execute(
            "SELECT id,name,path,COALESCE(description,'') FROM bash_scripts WHERE project_id=? ORDER BY id",
            (pid,),
        ):
            print(f"{sid:>3}  {name}  {path}  — {desc}")


def log_action(project: str | None, cwd: str, action: str, summary: str) -> None:
    with conn() as c:
        pid = _project_id(c, project)
        c.execute(
            "INSERT INTO directory_log(project_id, cwd, action, change_summary) VALUES(?,?,?,?)",
            (pid, cwd, action, summary),
        )


def show_log(n: int = 20) -> None:
    with conn() as c:
        rows = c.execute(
            """
            SELECT directory_log.id, COALESCE(projects.name,'(none)'), cwd, action,
                   COALESCE(change_summary,''), directory_log.created_at
            FROM directory_log
            LEFT JOIN projects ON projects.id = directory_log.project_id
            ORDER BY directory_log.id DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
        for lid, pname, cwd, action, summary, created in reversed(rows):
            print(f"{created}  [{pname}]  ({cwd})  {action}  -- {summary}")


def queue_add(project: str, command: str) -> None:
    with conn() as c:
        pid = get_or_create_project(c, project)
        cur = c.execute(
            "INSERT INTO queue(project_id, command) VALUES(?,?)", (pid, command)
        )
        print(cur.lastrowid)


def queue_list() -> None:
    with conn() as c:
        for qid, pname, status, cmd, created in c.execute(
            """
            SELECT queue.id, projects.name, status, command, queue.created_at
            FROM queue JOIN projects ON projects.id = queue.project_id
            ORDER BY queue.id
            """
        ):
            print(f"{qid:>3}  [{status}]  [{pname}]  {cmd}  ({created})")


def queue_pop(qid: int) -> None:
    # Atomic: only one agent can pop a given queue entry.
    with conn() as c:
        c.execute("BEGIN IMMEDIATE;")
        row = c.execute(
            "SELECT command, status FROM queue WHERE id=?", (qid,)
        ).fetchone()
        if not row:
            c.execute("COMMIT;")
            sys.exit(f"no queue entry {qid}")
        cmd, status = row
        if status != "queued":
            c.execute("COMMIT;")
            sys.exit(f"queue entry {qid} already {status}")
        c.execute(
            "UPDATE queue SET status='running' WHERE id=? AND status='queued'", (qid,)
        )
        c.execute("COMMIT;")
        print(cmd)


def queue_done(qid: int) -> None:
    with conn() as c:
        c.execute("UPDATE queue SET status='done' WHERE id=?", (qid,))


def current_set(project: str, todo_id: int) -> None:
    with conn() as c:
        pid = get_or_create_project(c, project)
        c.execute(
            """
            INSERT INTO current_task(id, project_id, todo_id, started_at)
            VALUES(1, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,
                                          todo_id=excluded.todo_id,
                                          started_at=excluded.started_at
            """,
            (pid, todo_id),
        )


def current_show() -> None:
    with conn() as c:
        row = c.execute(
            """
            SELECT projects.name, todos.id, todos.task, current_task.started_at
            FROM current_task
            JOIN projects ON projects.id = current_task.project_id
            JOIN todos ON todos.id = current_task.todo_id
            WHERE current_task.id = 1
            """
        ).fetchone()
        if not row:
            print("(no current task)")
            return
        pname, tid, task, started = row
        print(f"[{pname}]  #{tid}  {task}  (since {started})")


def current_clear() -> None:
    with conn() as c:
        c.execute("DELETE FROM current_task WHERE id=1;")


def set_project_path(name: str, path: str) -> None:
    with conn() as c:
        pid = get_or_create_project(c, name)
        c.execute("UPDATE projects SET path=? WHERE id=?", (path, pid))


def project_path(name: str) -> None:
    with conn() as c:
        row = c.execute("SELECT path FROM projects WHERE name=?", (name,)).fetchone()
        print(row[0] if row and row[0] else "")


def meta_set(key: str, value: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def meta_get(key: str) -> None:
    with conn() as c:
        row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        print(row[0] if row else "")


def meta_list() -> None:
    with conn() as c:
        for k, v in c.execute("SELECT key,value FROM meta ORDER BY key;"):
            print(f"{k}\t{v}")


def entry_add(name: str, path: str, kind: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO entrypoints(name,path,kind) VALUES(?,?,?)",
            (name, path, kind),
        )


def entry_list() -> None:
    with conn() as c:
        for eid, name, path, kind, last_run, last_rc in c.execute(
            "SELECT id,name,path,kind,COALESCE(last_run_at,''),COALESCE(last_rc,'') FROM entrypoints ORDER BY id"
        ):
            print(f"{eid:>3}  [{kind}]  {name}  {path}  last={last_run} rc={last_rc}")


def entry_clear() -> None:
    with conn() as c:
        c.execute("DELETE FROM entrypoints;")


def run_add(kind: str, command: str, rc: int, stdout_tail: str, stderr_tail: str, agent_uuid: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO runs(kind,command,rc,stdout_tail,stderr_tail,finished_at,agent_uuid) "
            "VALUES(?,?,?,?,?,datetime('now'),?)",
            (kind, command, rc, stdout_tail, stderr_tail, agent_uuid),
        )
        # update last_rc on matching entrypoint if any
        c.execute(
            "UPDATE entrypoints SET last_run_at=datetime('now'), last_rc=? "
            "WHERE path=(SELECT path FROM entrypoints WHERE path=? LIMIT 1)",
            (rc, command.split()[1] if len(command.split()) >= 2 else command),
        )


def run_list(n: int = 20) -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT id,kind,command,rc,started_at,finished_at FROM runs ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
        for rid, kind, cmd, rc, started, finished in reversed(rows):
            print(f"{finished or started}  #{rid}  [{kind}]  rc={rc}  {cmd}")


def run_last_stderr(n: int = 1) -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT id,command,rc,stderr_tail FROM runs ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        for rid, cmd, rc, stderr in reversed(rows):
            print(f"--- run #{rid}  rc={rc}  {cmd} ---")
            print(stderr or "")


def agent_claim(uuid: str, pid: int, cwd: str, action: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO agents(uuid,pid,cwd,action) VALUES(?,?,?,?)",
            (uuid, pid, cwd, action),
        )


def agent_update(uuid: str, action: str) -> None:
    with conn() as c:
        c.execute("UPDATE agents SET action=? WHERE uuid=?", (action, uuid))


def agent_release(uuid: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE agents SET finished_at=datetime('now') WHERE uuid=?", (uuid,)
        )


def agent_list() -> None:
    with conn() as c:
        for uuid, pid, cwd, action, started, finished in c.execute(
            "SELECT uuid,pid,cwd,action,started_at,COALESCE(finished_at,'') "
            "FROM agents ORDER BY started_at DESC LIMIT 30"
        ):
            state = "live" if not finished else "done"
            print(f"[{state}]  {uuid[:8]}  pid={pid}  {cwd}  -- {action}  ({started})")


def tool_def(name: str, description: str, input_schema: str, output_schema: str,
             executor_kind: str, executor: str, tags: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO tools(name, description, input_schema, output_schema, "
            "executor_kind, executor, tags) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "description=excluded.description, input_schema=excluded.input_schema, "
            "output_schema=excluded.output_schema, executor_kind=excluded.executor_kind, "
            "executor=excluded.executor, tags=excluded.tags",
            (name, description, input_schema, output_schema, executor_kind, executor, tags),
        )


def tool_get(name: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT description, input_schema, output_schema, executor_kind, executor, COALESCE(tags,'') "
            "FROM tools WHERE name=?",
            (name,),
        ).fetchone()
        if not r:
            sys.exit(f"no tool: {name}")
        import json as _json
        sys.stdout.write(_json.dumps({
            "name": name,
            "description": r[0],
            "input_schema": _json.loads(r[1]) if r[1] else {},
            "output_schema": _json.loads(r[2]) if r[2] else {},
            "executor_kind": r[3],
            "executor": r[4],
            "tags": r[5],
        }))


def tool_list() -> None:
    with conn() as c:
        for name, desc, ek, tags in c.execute(
            "SELECT name, COALESCE(description,''), executor_kind, COALESCE(tags,'') "
            "FROM tools ORDER BY name"
        ):
            print(f"{name:<24}  [{ek}]  {tags:<24}  {desc}")


def tool_delete(name: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM tools WHERE name=?", (name,))


def workflow_def(name: str, description: str, steps_json: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO workflows(name, description, steps_json) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
            "steps_json=excluded.steps_json",
            (name, description, steps_json),
        )


def workflow_get(name: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT description, steps_json, COALESCE(last_used_at,''), use_count "
            "FROM workflows WHERE name=?",
            (name,),
        ).fetchone()
        if not r:
            sys.exit(f"no workflow: {name}")
        import json as _json
        sys.stdout.write(_json.dumps({
            "name": name,
            "description": r[0],
            "steps": _json.loads(r[1]) if r[1] else [],
            "last_used_at": r[2],
            "use_count": r[3],
        }))


def workflow_list() -> None:
    with conn() as c:
        for name, desc, last_used, use_count in c.execute(
            "SELECT name, COALESCE(description,''), COALESCE(last_used_at,''), use_count "
            "FROM workflows ORDER BY use_count DESC, name"
        ):
            print(f"{name:<24}  used={use_count:<3}  last={last_used:<20}  {desc}")


def workflow_used(name: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE workflows SET last_used_at=datetime('now'), "
            "use_count=use_count+1 WHERE name=?",
            (name,),
        )


def workflow_search(query: str) -> None:
    """Cheap substring match across name/description/steps. JSON output."""
    import json as _json
    q = query.lower()
    with conn() as c:
        rows = c.execute(
            "SELECT name, COALESCE(description,''), steps_json, use_count, "
            "COALESCE(last_used_at,'') FROM workflows"
        ).fetchall()
    scored = []
    for name, desc, steps, use_count, last_used in rows:
        haystack = (name + " " + desc + " " + (steps or "")).lower()
        score = 0
        for w in q.split():
            if w in haystack:
                score += 1
        if not q:  # no query — return all sorted by use_count
            score = use_count
        if q == "" or score > 0:
            scored.append((score, name, desc, use_count, last_used))
    scored.sort(reverse=True)
    sys.stdout.write(_json.dumps([
        {"name": n, "description": d, "score": s, "use_count": uc, "last_used_at": lu}
        for s, n, d, uc, lu in scored
    ]))


def agent_def(name: str, model: str, prompt_template: str, description: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO agent_defs(name, model, prompt_template, description) "
            "VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
            "model=excluded.model, prompt_template=excluded.prompt_template, "
            "description=excluded.description",
            (name, model, prompt_template, description),
        )


def agent_def_get(name: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT model, prompt_template, COALESCE(description,'') "
            "FROM agent_defs WHERE name=?",
            (name,),
        ).fetchone()
        if not r:
            sys.exit(f"no agent: {name}")
        # tab-separated so bash can split; template may contain newlines so emit
        # a sentinel-bounded payload.
        model, tmpl, desc = r
        print(f"MODEL\t{model}")
        print(f"DESC\t{desc}")
        print("TEMPLATE_BEGIN")
        print(tmpl, end="")
        print("\nTEMPLATE_END")


def agent_def_list() -> None:
    with conn() as c:
        for name, model, desc in c.execute(
            "SELECT name, model, COALESCE(description,'') FROM agent_defs ORDER BY name"
        ):
            print(f"{name:<24}  [{model}]  {desc}")


def agent_def_delete(name: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM agent_defs WHERE name=?", (name,))


def swarm_def(name: str, description: str, steps_json: str, loop_until: str = "", max_iters: int = 10) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO swarm_defs(name, description, steps_json, loop_until, max_iters) "
            "VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
            "description=excluded.description, steps_json=excluded.steps_json, "
            "loop_until=excluded.loop_until, max_iters=excluded.max_iters",
            (name, description, steps_json, loop_until, max_iters),
        )


def swarm_def_get(name: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT description, steps_json, COALESCE(loop_until,''), max_iters "
            "FROM swarm_defs WHERE name=?",
            (name,),
        ).fetchone()
        if not r:
            sys.exit(f"no swarm: {name}")
        desc, steps, loop, max_iters = r
        # Emit JSON — bash can carry it through command substitution and parse with jq.
        import json as _json
        out = {
            "description": desc,
            "steps": _json.loads(steps),
            "loop_until": loop,
            "max_iters": max_iters,
        }
        sys.stdout.write(_json.dumps(out))


def swarm_def_list() -> None:
    with conn() as c:
        for name, desc, loop, max_iters in c.execute(
            "SELECT name, COALESCE(description,''), COALESCE(loop_until,''), max_iters "
            "FROM swarm_defs ORDER BY name"
        ):
            loop_tag = f" loop_until={loop!r}" if loop else ""
            print(f"{name:<24}  max={max_iters}{loop_tag}  {desc}")


def swarm_run_start(swarm_name: str, vars_json: str, agent_uuid: str) -> None:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO swarm_runs(swarm_name, vars_json, agent_uuid) VALUES(?,?,?)",
            (swarm_name, vars_json, agent_uuid),
        )
        print(cur.lastrowid)


def swarm_run_step_add(
    run_id: int, iteration: int, step_idx: int, agent_name: str,
    inputs_json: str, output: str, done_seen: int,
) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO swarm_run_steps(swarm_run_id, iteration, step_idx, "
            "agent_name, inputs_json, output, done_seen, finished_at) "
            "VALUES(?,?,?,?,?,?,?,datetime('now'))",
            (run_id, iteration, step_idx, agent_name, inputs_json, output, done_seen),
        )


def swarm_run_end(run_id: int, status: str, iterations: int) -> None:
    with conn() as c:
        c.execute(
            "UPDATE swarm_runs SET status=?, ended_at=datetime('now'), iterations=? "
            "WHERE id=?",
            (status, iterations, run_id),
        )


def swarm_run_show(run_id: int) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT swarm_name, status, started_at, COALESCE(ended_at,''), iterations "
            "FROM swarm_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if not r:
            sys.exit(f"no swarm run #{run_id}")
        sname, status, started, ended, iters = r
        print(f"# swarm run #{run_id}  {sname}  [{status}]  iters={iters}")
        print(f"  started: {started}\n  ended:   {ended or '-'}\n")
        for itr, idx, agent, output, done, finished in c.execute(
            "SELECT iteration, step_idx, agent_name, output, done_seen, finished_at "
            "FROM swarm_run_steps WHERE swarm_run_id=? ORDER BY id",
            (run_id,),
        ):
            mark = "✓" if done else "⚠"
            head = (output or "").splitlines()[0] if output else ""
            print(f"  iter={itr} step={idx} {agent:<18} {mark} {finished}  -> {head[:80]}")


def swarm_run_last() -> None:
    with conn() as c:
        r = c.execute(
            "SELECT id FROM swarm_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if r:
            swarm_run_show(r[0])


# ---- chain runs --------------------------------------------------------
# Mirrors the swarm_run_* pattern but for cc -chain. Each `cc -chain` run
# inserts one chain_runs row + N chain_run_steps rows.

def chain_run_start(spec: str, agent_uuid: str) -> None:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO chain_runs(spec, agent_uuid) VALUES(?,?)",
            (spec, agent_uuid),
        )
        print(cur.lastrowid)


def chain_run_step_add(
    run_id: int, step_idx: int, op: str, isolated: int,
    context_in: str, prompt: str, output: str,
    ms_elapsed: int, from_cache: int,
) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO chain_run_steps(chain_run_id, step_idx, op, isolated, "
            "context_in, prompt, output, ms_elapsed, from_cache, finished_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))",
            (run_id, step_idx, op, isolated, context_in, prompt, output,
             ms_elapsed, from_cache),
        )


def chain_run_end(run_id: int, status: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE chain_runs SET status=?, ended_at=datetime('now') WHERE id=?",
            (status, run_id),
        )


def chain_run_show(run_id: int) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT spec, status, started_at, COALESCE(ended_at,''), "
            "COALESCE(agent_uuid,'') "
            "FROM chain_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if not r:
            sys.exit(f"no chain run #{run_id}")
        spec, status, started, ended, agent = r
        spec_preview = spec if len(spec) <= 120 else spec[:117] + "..."
        print(f"# chain run #{run_id}  [{status}]  agent={agent[:8]}")
        print(f"  spec:    {spec_preview}")
        print(f"  started: {started}")
        print(f"  ended:   {ended or '-'}")
        # Sum timing
        total = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(ms_elapsed),0), "
            "COALESCE(SUM(from_cache),0) FROM chain_run_steps WHERE chain_run_id=?",
            (run_id,),
        ).fetchone()
        if total:
            n, ms, hits = total
            print(f"  steps:   {n}  total_ms={ms}  cache_hits={hits}/{n}")
        print()
        for idx, op, iso, prompt, output, ms, cache, finished in c.execute(
            "SELECT step_idx, COALESCE(op,'start'), isolated, prompt, output, "
            "ms_elapsed, from_cache, finished_at "
            "FROM chain_run_steps WHERE chain_run_id=? ORDER BY id",
            (run_id,),
        ):
            iso_tag = " cc{}" if iso else ""
            cache_tag = " [cache]" if cache else ""
            phead = (prompt or "").splitlines()[0] if prompt else ""
            ohead = (output or "").splitlines()[0] if output else ""
            print(f"  step {idx} [{op}{iso_tag}]  {ms}ms{cache_tag}")
            print(f"    prompt: {phead[:80]}")
            print(f"    output: {ohead[:80]}")


def chain_run_last() -> None:
    with conn() as c:
        r = c.execute(
            "SELECT id FROM chain_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if r:
            chain_run_show(r[0])
        else:
            print("(no chain runs yet)")


def chain_run_list(n: int = 20) -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT cr.id, cr.status, cr.started_at, COALESCE(cr.ended_at,'-'), "
            "       (SELECT COUNT(*) FROM chain_run_steps WHERE chain_run_id=cr.id), "
            "       (SELECT COALESCE(SUM(ms_elapsed),0) FROM chain_run_steps "
            "        WHERE chain_run_id=cr.id), "
            "       cr.spec "
            "FROM chain_runs cr ORDER BY cr.id DESC LIMIT ?",
            (n,),
        ).fetchall()
        if not rows:
            print("(no chain runs)")
            return
        for rid, status, started, ended, n_steps, total_ms, spec in rows:
            spec_short = (spec[:60] + '...') if len(spec) > 60 else spec
            print(f"  #{rid:<4} [{status:<7}] steps={n_steps} ms={total_ms} "
                  f"{started}  {spec_short}")


# ---- capability cards (tiny-model-drafted, per-opcode) -----------------

def card_upsert(opcode: str, drafted_by: str, card_json: str,
                source: str = "tiny-chain") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO capability_cards(opcode, drafted_by, card_json, source) "
            "VALUES(?,?,?,?) "
            "ON CONFLICT(opcode) DO UPDATE SET "
            "  drafted_by=excluded.drafted_by, "
            "  drafted_at=datetime('now'), "
            "  card_json=excluded.card_json, "
            "  source=excluded.source",
            (opcode, drafted_by, card_json, source),
        )


def card_get(opcode: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT opcode, drafted_by, drafted_at, card_json, source "
            "FROM capability_cards WHERE opcode=?",
            (opcode,),
        ).fetchone()
        if not r:
            sys.exit(f"no card for opcode: {opcode}")
        op, by, at, card, src = r
        print(f"# capability card: {op}")
        print(f"  drafted_by: {by}  at {at}  src={src}")
        print()
        print(card)


def card_list() -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT opcode, drafted_by, drafted_at, "
            "       length(card_json) AS bytes "
            "FROM capability_cards ORDER BY opcode"
        ).fetchall()
        if not rows:
            print("(no cards yet — run `cc -author-cards <opcode>` to draft)")
            return
        for op, by, at, n in rows:
            print(f"  {op:<32}  {by:<24}  {n:>5} bytes  {at}")


def card_delete(opcode: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM capability_cards WHERE opcode=?", (opcode,))


# ---- GUI cards (per-opcode widget spec) --------------------------------

def gui_card_upsert(opcode: str, drafted_by: str, card_json: str,
                    source: str = "tiny-chain") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO gui_cards(opcode, drafted_by, card_json, source) "
            "VALUES(?,?,?,?) "
            "ON CONFLICT(opcode) DO UPDATE SET "
            "  drafted_by=excluded.drafted_by, "
            "  drafted_at=datetime('now'), "
            "  card_json=excluded.card_json, "
            "  source=excluded.source",
            (opcode, drafted_by, card_json, source),
        )


def gui_card_get(opcode: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT opcode, drafted_by, drafted_at, card_json, source "
            "FROM gui_cards WHERE opcode=?",
            (opcode,),
        ).fetchone()
        if not r:
            sys.exit(f"no gui card for opcode: {opcode}")
        op, by, at, card, src = r
        print(f"# gui card: {op}")
        print(f"  drafted_by: {by}  at {at}  src={src}")
        print()
        print(card)


def gui_card_list() -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT opcode, drafted_by, drafted_at, length(card_json) "
            "FROM gui_cards ORDER BY opcode"
        ).fetchall()
        if not rows:
            print("(no gui cards yet — run `cc -author-gui-cards <opcode>`)")
            return
        for op, by, at, n in rows:
            print(f"  {op:<32}  {by:<24}  {n:>5} bytes  {at}")


def gui_card_delete(opcode: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM gui_cards WHERE opcode=?", (opcode,))


# ---- workflow templates (Claude-authored recipes) ----------------------

def template_add(name: str, primary_opcode: str, description: str,
                 tags: str, template_json: str, preconditions_json: str,
                 fallbacks_json: str, authored_by: str,
                 author_prompt_hash: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO workflow_templates(name, primary_opcode, description, "
            "  tags, template_json, preconditions_json, fallbacks_json, "
            "  authored_by, author_prompt_hash) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "  primary_opcode=excluded.primary_opcode, "
            "  description=excluded.description, "
            "  tags=excluded.tags, "
            "  template_json=excluded.template_json, "
            "  preconditions_json=excluded.preconditions_json, "
            "  fallbacks_json=excluded.fallbacks_json, "
            "  authored_by=excluded.authored_by, "
            "  author_prompt_hash=excluded.author_prompt_hash",
            (name, primary_opcode, description, tags, template_json,
             preconditions_json, fallbacks_json, authored_by,
             author_prompt_hash),
        )


def template_list() -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT name, primary_opcode, COALESCE(tags,''), authored_by, "
            "       use_count, description "
            "FROM workflow_templates ORDER BY use_count DESC, name"
        ).fetchall()
        if not rows:
            print("(no templates yet — run `cc -authorize-templates --opcode <X>` "
                  "or seed with the path-builder)")
            return
        for name, op, tags, by, used, desc in rows:
            desc_short = (desc[:80] + '...') if len(desc) > 80 else desc
            print(f"  {name:<36}  [{op}]  used={used}  by={by}")
            print(f"      tags: {tags}")
            print(f"      {desc_short}")


def template_show(name: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT name, primary_opcode, description, tags, template_json, "
            "       preconditions_json, fallbacks_json, authored_by, "
            "       use_count, created_at "
            "FROM workflow_templates WHERE name=?",
            (name,),
        ).fetchone()
        if not r:
            sys.exit(f"no template named: {name}")
        n, op, desc, tags, tpl, pre, fb, by, used, ts = r
        print(f"# template: {n}")
        print(f"  primary_opcode: {op}")
        print(f"  authored_by:    {by}  at {ts}  use_count={used}")
        print(f"  tags:           {tags}")
        print(f"  description:")
        print(f"    {desc}")
        print()
        print("## steps (template_json)")
        print(tpl)
        if pre:
            print()
            print("## preconditions")
            print(pre)
        if fb:
            print()
            print("## fallbacks")
            print(fb)


def template_delete(name: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM workflow_templates WHERE name=?", (name,))


def template_used(name: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE workflow_templates SET "
            "  use_count=use_count+1, last_used_at=datetime('now') "
            "WHERE name=?",
            (name,),
        )


# ---- workflow jobs (per-project execution state — W4 scaffolding) ------
# The executor (cc -job, cc -job-step) is not yet built. These helpers
# provide schema + read-only access so the table is ready when the
# runner lands. All write functions accept full state explicitly — the
# runner constructs the state, db.py just persists.

def job_start(template_name: str, user_request: str,
              context_json: str = "{}", agent_uuid: str = "") -> None:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO workflow_jobs(template_name, user_request, "
            "  context_json, agent_uuid) VALUES(?,?,?,?)",
            (template_name or None, user_request, context_json, agent_uuid),
        )
        print(cur.lastrowid)


def job_set_status(job_id: int, status: str,
                   end: int = 0) -> None:
    end_clause = ", ended_at=datetime('now')" if end else ""
    with conn() as c:
        c.execute(
            f"UPDATE workflow_jobs SET status=?{end_clause} WHERE id=?",
            (status, job_id),
        )


def job_advance(job_id: int, current_step: int,
                context_json: str = "") -> None:
    with conn() as c:
        if context_json:
            c.execute(
                "UPDATE workflow_jobs SET current_step=?, "
                "context_json=? WHERE id=?",
                (current_step, context_json, job_id),
            )
        else:
            c.execute(
                "UPDATE workflow_jobs SET current_step=? WHERE id=?",
                (current_step, job_id),
            )


def job_step_add(
    job_id: int, step_idx: int, opcode: str, purpose: str,
    chosen_model: str, inputs_json: str, output: str,
    human_checkpoint_type: str, human_decision: str, human_notes: str,
    ms_elapsed: int,
) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO workflow_job_steps(job_id, step_idx, opcode, "
            "  purpose, chosen_model, inputs_json, output, "
            "  human_checkpoint_type, human_decision, human_notes, "
            "  ms_elapsed, finished_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (job_id, step_idx, opcode, purpose, chosen_model,
             inputs_json, output, human_checkpoint_type or None,
             human_decision or None, human_notes or None, ms_elapsed),
        )


def job_show(job_id: int) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT id, template_name, user_request, current_step, "
            "  status, started_at, COALESCE(ended_at,''), "
            "  COALESCE(agent_uuid,''), COALESCE(context_json,'{}') "
            "FROM workflow_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not r:
            sys.exit(f"no job #{job_id}")
        jid, tpl, req, step, status, started, ended, agent, ctx = r
        print(f"# job #{jid}  [{status}]  template={tpl or '(ad-hoc)'}")
        print(f"  request:   {req}")
        print(f"  step:      {step}")
        print(f"  agent:     {agent[:8] if agent else '-'}")
        print(f"  started:   {started}")
        print(f"  ended:     {ended or '-'}")
        steps = c.execute(
            "SELECT step_idx, opcode, COALESCE(purpose,''), "
            "  COALESCE(chosen_model,''), COALESCE(output,''), "
            "  COALESCE(human_decision,''), ms_elapsed, finished_at "
            "FROM workflow_job_steps WHERE job_id=? ORDER BY id",
            (job_id,),
        ).fetchall()
        if not steps:
            print("\n  (no steps recorded yet)")
            return
        print(f"\n  steps:")
        for idx, op, purpose, model, output, decision, ms, fin in steps:
            hd = f" [{decision}]" if decision else ""
            mt = f" via {model}" if model else ""
            print(f"  ─ step {idx} {op}{mt}{hd} ({ms}ms)")
            if purpose:
                print(f"      purpose: {purpose}")
            if output:
                head = output.splitlines()[0] if output else ""
                print(f"      output:  {head[:80]}")


def job_list(n: int = 20) -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT j.id, COALESCE(j.template_name,'(ad-hoc)'), j.status, "
            "  j.started_at, COALESCE(j.ended_at,'-'), "
            "  (SELECT COUNT(*) FROM workflow_job_steps WHERE job_id=j.id), "
            "  substr(j.user_request,1,60) "
            "FROM workflow_jobs j ORDER BY j.id DESC LIMIT ?",
            (n,),
        ).fetchall()
        if not rows:
            print("(no jobs yet)")
            return
        for jid, tpl, status, started, ended, n_steps, req in rows:
            print(f"  #{jid:<4} [{status:<14}] steps={n_steps}  tpl={tpl:<28}"
                  f"  {started}  {req}")


def job_last() -> None:
    with conn() as c:
        r = c.execute(
            "SELECT id FROM workflow_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not r:
            print("(no jobs yet)")
            return
        job_show(r[0])


# ---- DAG cache (hash-addressed) ----------------------------------------

def dag_node_upsert(node_id: str, node_kind: str, name: str,
                    payload_json: str, mui_component: str = "",
                    parent_node: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO dag_nodes(node_id, node_kind, name, payload_json, "
            "  mui_component, parent_node) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(node_id) DO UPDATE SET "
            "  node_kind=excluded.node_kind, "
            "  name=excluded.name, "
            "  payload_json=excluded.payload_json, "
            "  mui_component=excluded.mui_component, "
            "  parent_node=excluded.parent_node, "
            "  updated_at=datetime('now'), "
            "  stale=0",
            (node_id, node_kind, name, payload_json,
             mui_component or None, parent_node or None),
        )


def dag_edge_upsert(edge_id: str, src: str, dst: str, kind: str,
                    weight: float = 1.0, payload_json: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO dag_edges(edge_id, src_node, dst_node, edge_kind, "
            "  weight, payload_json) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(edge_id) DO UPDATE SET "
            "  weight=excluded.weight, "
            "  payload_json=excluded.payload_json",
            (edge_id, src, dst, kind, weight, payload_json or None),
        )


def dag_chain_upsert(chain_id: str, src_opcode: str, dst_opcode: str,
                     chain_json: str, score: float, intent_tags: str = "",
                     gui_dag_root: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO dag_chains(chain_id, src_opcode, dst_opcode, "
            "  chain_json, score, intent_tags, gui_dag_root) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(chain_id) DO UPDATE SET "
            "  chain_json=excluded.chain_json, "
            "  score=excluded.score, "
            "  intent_tags=excluded.intent_tags, "
            "  gui_dag_root=excluded.gui_dag_root, "
            "  updated_at=datetime('now'), "
            "  stale=0",
            (chain_id, src_opcode, dst_opcode, chain_json, score,
             intent_tags or None, gui_dag_root or None),
        )


def dag_node_get(node_id: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT node_id, node_kind, name, payload_json, "
            "  COALESCE(mui_component,''), COALESCE(parent_node,''), "
            "  created_at, updated_at, stale "
            "FROM dag_nodes WHERE node_id=?",
            (node_id,),
        ).fetchone()
        if not r:
            sys.exit(f"no dag_node: {node_id}")
        nid, kind, name, payload, mui, parent, created, updated, stale = r
        st = " [STALE]" if stale else ""
        print(f"# dag_node {nid}{st}")
        print(f"  kind:    {kind}")
        print(f"  name:    {name}")
        print(f"  mui:     {mui or '-'}")
        print(f"  parent:  {parent or '-'}")
        print(f"  created: {created}")
        print(f"  updated: {updated}")
        print()
        print("  payload:")
        print(payload)
        # outgoing edges
        edges_out = c.execute(
            "SELECT edge_kind, dst_node, weight FROM dag_edges "
            "WHERE src_node=? ORDER BY edge_kind, weight DESC LIMIT 20",
            (node_id,),
        ).fetchall()
        if edges_out:
            print()
            print(f"  outgoing edges ({len(edges_out)}):")
            for k, d, w in edges_out:
                print(f"    --[{k} w={w}]-->  {d}")


def dag_chain_get(chain_id: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT chain_id, src_opcode, dst_opcode, chain_json, score, "
            "  COALESCE(intent_tags,''), COALESCE(gui_dag_root,''), "
            "  created_at, updated_at, stale, hit_count "
            "FROM dag_chains WHERE chain_id=?",
            (chain_id,),
        ).fetchone()
        if not r:
            sys.exit(f"no dag_chain: {chain_id}")
        cid, src, dst, chain, score, tags, gui, created, updated, stale, hits = r
        st = " [STALE]" if stale else ""
        print(f"# dag_chain {cid}{st}")
        print(f"  src→dst: {src} → {dst}")
        print(f"  score:   {score}")
        print(f"  hits:    {hits}")
        print(f"  tags:    {tags or '-'}")
        print(f"  gui:     {gui or '-'}")
        print(f"  updated: {updated}")
        print()
        print(f"  chain: {chain}")


def dag_status() -> None:
    with conn() as c:
        n_nodes = c.execute("SELECT COUNT(*) FROM dag_nodes").fetchone()[0]
        n_edges = c.execute("SELECT COUNT(*) FROM dag_edges").fetchone()[0]
        n_chains = c.execute("SELECT COUNT(*) FROM dag_chains").fetchone()[0]
        n_stale_n = c.execute(
            "SELECT COUNT(*) FROM dag_nodes WHERE stale=1").fetchone()[0]
        n_stale_c = c.execute(
            "SELECT COUNT(*) FROM dag_chains WHERE stale=1").fetchone()[0]
        n_pending = c.execute(
            "SELECT COUNT(*) FROM dag_build_queue WHERE status='pending'"
        ).fetchone()[0]
        n_running = c.execute(
            "SELECT COUNT(*) FROM dag_build_queue WHERE status='running'"
        ).fetchone()[0]
        n_done = c.execute(
            "SELECT COUNT(*) FROM dag_build_queue WHERE status='done'"
        ).fetchone()[0]
        n_failed = c.execute(
            "SELECT COUNT(*) FROM dag_build_queue WHERE status='failed'"
        ).fetchone()[0]
        kinds = c.execute(
            "SELECT node_kind, COUNT(*) FROM dag_nodes GROUP BY node_kind"
        ).fetchall()
        ekinds = c.execute(
            "SELECT edge_kind, COUNT(*) FROM dag_edges GROUP BY edge_kind"
        ).fetchall()
        hot = c.execute(
            "SELECT chain_id, src_opcode, dst_opcode, hit_count "
            "FROM dag_chains ORDER BY hit_count DESC LIMIT 5"
        ).fetchall()
        print("# dag cache status")
        print(f"  nodes:    {n_nodes}  (stale: {n_stale_n})")
        for k, n in kinds:
            print(f"      {k:<14} {n}")
        print(f"  edges:    {n_edges}")
        for k, n in ekinds:
            print(f"      {k:<22} {n}")
        print(f"  chains:   {n_chains}  (stale: {n_stale_c})")
        print(f"  queue:    pending={n_pending} running={n_running} "
              f"done={n_done} failed={n_failed}")
        if hot:
            print()
            print("  top hit chains:")
            for cid, s, d, h in hot:
                print(f"    {cid[:12]}…  {s} → {d}  hits={h}")


def dag_queue_add(task_kind: str, target_id: str, priority: int = 0) -> None:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO dag_build_queue(task_kind, target_id, priority) "
            "VALUES(?,?,?)",
            (task_kind, target_id, priority),
        )
        print(cur.lastrowid)


def dag_queue_pop() -> None:
    """Pop one pending task atomically. Prints task as JSON or empty."""
    import json as _json
    with conn() as c:
        c.execute("BEGIN IMMEDIATE;")
        r = c.execute(
            "SELECT id, task_kind, target_id, priority "
            "FROM dag_build_queue WHERE status='pending' "
            "ORDER BY priority DESC, id LIMIT 1"
        ).fetchone()
        if not r:
            c.execute("COMMIT;")
            return
        c.execute(
            "UPDATE dag_build_queue SET status='running', "
            "started_at=datetime('now') WHERE id=?",
            (r[0],),
        )
        c.execute("COMMIT;")
        print(_json.dumps({"id": r[0], "task_kind": r[1],
                           "target_id": r[2], "priority": r[3]}))


def dag_queue_complete(task_id: int, status: str,
                       ms_elapsed: int = 0, error: str = "") -> None:
    with conn() as c:
        c.execute(
            "UPDATE dag_build_queue SET status=?, finished_at=datetime('now'), "
            "ms_elapsed=?, error_text=? WHERE id=?",
            (status, ms_elapsed, error or None, task_id),
        )


def dag_mark_chain_stale(chain_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE dag_chains SET stale=1 WHERE chain_id=?",
                  (chain_id,))


def dag_mark_node_stale(node_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE dag_nodes SET stale=1 WHERE node_id=?",
                  (node_id,))


def dag_chain_hit(chain_id: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE dag_chains SET hit_count=hit_count+1 WHERE chain_id=?",
            (chain_id,),
        )


# ---- DAG runtime lookups (zero-compute — served from the cache) -------
# These three commands replace runtime path_builder.py subprocess calls
# with O(1)/O(N) sqlite queries. They never invoke ollama, never spawn
# python processes for compute. The cache must be warm
# (`cc -dag-bootstrap`) for these to return useful data.

def dag_successors(opcode: str, top: int = 5) -> None:
    """Top-N ranked successors for an opcode. Reads the precomputed
    succession edges (src=this_opcode, kind=succession, weight=score)."""
    with conn() as c:
        # Resolve opcode name -> node_id
        r = c.execute(
            "SELECT node_id FROM dag_nodes "
            "WHERE node_kind='opcode' AND name=?",
            (opcode,),
        ).fetchone()
        if not r:
            # Soft error: suggest close matches via case-insensitive prefix.
            close = c.execute(
                "SELECT name FROM dag_nodes "
                "WHERE node_kind='opcode' AND lower(name) LIKE ? "
                "ORDER BY name LIMIT 5",
                (opcode.lower()[:4] + '%',),
            ).fetchall()
            print(f"(no opcode named {opcode!r} in the dag cache)")
            if close:
                print("  did you mean:")
                for (n,) in close:
                    print(f"    - {n}")
            else:
                print("  (run `cc -dag-bootstrap` if the cache is empty)")
            return
        src = r[0]
        rows = c.execute(
            "SELECT n.name, e.weight, COALESCE(e.payload_json,'{}'), n.payload_json "
            "FROM dag_edges e JOIN dag_nodes n ON n.node_id=e.dst_node "
            "WHERE e.src_node=? AND e.edge_kind='succession' "
            "ORDER BY e.weight DESC LIMIT ?",
            (src, top),
        ).fetchall()
        if not rows:
            print(f"(no successors cached for {opcode!r} — "
                  "run `cc -dag-bootstrap`)")
            return
        print(f"# successors of {opcode}  (top {len(rows)} of cached)")
        import json as _json
        for name, w, payload, node_payload in rows:
            try:
                p = _json.loads(payload) if payload else {}
            except _json.JSONDecodeError:
                p = {}
            try:
                np = _json.loads(node_payload) if node_payload else {}
            except _json.JSONDecodeError:
                np = {}
            via = ",".join(p.get("via") or [])
            era = np.get("era", "?")
            layer = np.get("layer", "?")
            print(f"  {name:<34}  weight={w:<5}  era={era}  L{layer}  "
                  f"via=[{via}]")


def dag_chains_from(opcode: str, top: int = 10) -> None:
    """Top-N cached chains that START with this opcode (sorted by score)."""
    with conn() as c:
        rows = c.execute(
            "SELECT chain_id, score, dst_opcode, chain_json, "
            "  COALESCE(intent_tags,''), hit_count "
            "FROM dag_chains WHERE src_opcode=? "
            "ORDER BY score DESC LIMIT ?",
            (opcode, top),
        ).fetchall()
        if not rows:
            print(f"(no chains cached from {opcode!r})")
            return
        print(f"# chains starting from {opcode}  ({len(rows)} cached)")
        for cid, score, dst, chain_j, tags, hits in rows:
            try:
                import json as _json
                chain = _json.loads(chain_j)
                rendered = " → ".join(chain)
            except _json.JSONDecodeError:
                rendered = chain_j
            print(f"  {cid[:12]}…  score={score:<5}  hits={hits}  {rendered}")


def dag_chains_pair(src_mod: str, dst_mod: str, top: int = 10) -> None:
    """Top-N cached chains matching src/dst modality tags."""
    needle = f"src:{src_mod},dst:{dst_mod}"
    with conn() as c:
        rows = c.execute(
            "SELECT chain_id, score, src_opcode, dst_opcode, chain_json, hit_count "
            "FROM dag_chains WHERE intent_tags=? "
            "ORDER BY score DESC LIMIT ?",
            (needle, top),
        ).fetchall()
        if not rows:
            print(f"(no chains cached for {src_mod} → {dst_mod} — "
                  "run `cc -dag-bootstrap`)")
            return
        print(f"# chains {src_mod} → {dst_mod}  ({len(rows)} cached)")
        import json as _json
        for cid, score, sop, dop, chain_j, hits in rows:
            try:
                chain = _json.loads(chain_j)
                rendered = " → ".join(chain)
            except _json.JSONDecodeError:
                rendered = chain_j
            print(f"  {cid[:12]}…  score={score:<5}  hits={hits}  {rendered}")


def phase_start(project: str, name: str) -> None:
    with conn() as c:
        c.execute("BEGIN IMMEDIATE;")
        pid = get_or_create_project(c, project)
        # close any existing active phase for this project
        c.execute(
            "UPDATE phases SET status='closed', ended_at=datetime('now') "
            "WHERE project_id=? AND status='active'",
            (pid,),
        )
        cur = c.execute(
            "INSERT INTO phases(project_id, name) VALUES(?, ?)", (pid, name)
        )
        c.execute("COMMIT;")
        print(cur.lastrowid)


def phase_active(project: str) -> None:
    with conn() as c:
        pid = _project_id(c, project)
        if pid is None:
            print("")
            return
        row = c.execute(
            "SELECT id, name FROM phases WHERE project_id=? AND status='active' "
            "ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if row:
            print(f"{row[0]}\t{row[1]}")
        else:
            print("")


def phase_step_add(
    phase_id: int,
    model: str,
    prompt: str,
    response: str,
    done_seen: int,
    agent_uuid: str,
) -> None:
    with conn() as c:
        c.execute("BEGIN IMMEDIATE;")
        idx = c.execute(
            "SELECT COALESCE(MAX(step_idx)+1, 1) FROM phase_steps WHERE phase_id=?",
            (phase_id,),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO phase_steps(phase_id, step_idx, model, prompt, response, "
            "done_seen, finished_at, agent_uuid) "
            "VALUES(?,?,?,?,?,?,datetime('now'),?)",
            (phase_id, idx, model, prompt, response, done_seen, agent_uuid),
        )
        c.execute("COMMIT;")
        print(idx)


def phase_context(phase_id: int, n_steps: int = 10) -> None:
    """Emit prior step outputs as a markdown block, to be prepended to the
    next step's prompt by the parent (the 'tween level')."""
    with conn() as c:
        rows = c.execute(
            "SELECT step_idx, model, response, done_seen FROM phase_steps "
            "WHERE phase_id=? ORDER BY step_idx DESC LIMIT ?",
            (phase_id, n_steps),
        ).fetchall()
        if not rows:
            return
        rows = list(reversed(rows))
        print("# Previous phase outputs (read-only context — do not repeat)\n")
        for idx, model, resp, done in rows:
            mark = "✓" if done else "⚠ partial"
            print(f"## step {idx} [{model}] {mark}")
            print(resp or "")
            print()


def phase_show(phase_id: int) -> None:
    with conn() as c:
        row = c.execute(
            "SELECT p.name, p.status, p.started_at, p.ended_at, COALESCE(pr.name,''), "
            "COALESCE(p.summary,'') "
            "FROM phases p LEFT JOIN projects pr ON pr.id = p.project_id "
            "WHERE p.id=?",
            (phase_id,),
        ).fetchone()
        if not row:
            sys.exit(f"no phase #{phase_id}")
        name, status, started, ended, pname, summary = row
        print(f"# phase #{phase_id}  [{pname}]  {name}  [{status}]")
        print(f"  started: {started}")
        print(f"  ended:   {ended or '-'}")
        if summary:
            print(f"  summary: {summary}")
        print()
        for idx, model, prompt, response, done, finished in c.execute(
            "SELECT step_idx, model, prompt, response, done_seen, finished_at "
            "FROM phase_steps WHERE phase_id=? ORDER BY step_idx",
            (phase_id,),
        ):
            mark = "✓" if done else "⚠"
            print(f"--- step {idx} [{model}] {mark}  ({finished}) ---")
            print(f"  prompt:   {(prompt or '')[:200]}")
            print(f"  response: {(response or '')[:400]}")
            print()


def phase_end(phase_id: int, summary: str = "") -> None:
    with conn() as c:
        c.execute(
            "UPDATE phases SET status='closed', ended_at=datetime('now'), summary=? "
            "WHERE id=?",
            (summary, phase_id),
        )


def phase_list(project: str | None) -> None:
    with conn() as c:
        pid = _project_id(c, project)
        if pid is None:
            return
        for phid, name, status, started, ended, summary in c.execute(
            "SELECT id, name, status, started_at, COALESCE(ended_at,''), COALESCE(summary,'') "
            "FROM phases WHERE project_id=? ORDER BY id DESC LIMIT 30",
            (pid,),
        ):
            mark = "▶" if status == "active" else "■"
            print(f"{mark} #{phid:>3}  [{status}]  {name}  ({started}..{ended})  {summary}")


def chat_exists_by_hash(content_hash: str) -> None:
    with conn() as c:
        r = c.execute(
            "SELECT id FROM chats WHERE content_hash=?", (content_hash,)
        ).fetchone()
        print(r[0] if r else "")


def chat_add(
    project: str,
    scope_cwd: str,
    session_id: str,
    source: str,
    agent_uuid: str,
    started_at: str,
    finished_at: str,
    message_count: int,
    transcript_path: str,
    git_branch: str,
    forked_from: str,
    content_hash: str,
) -> None:
    with conn() as c:
        pid = get_or_create_project(c, project)
        try:
            cur = c.execute(
                """
                INSERT INTO chats(project_id, scope_cwd, session_id, source,
                                  agent_uuid, started_at, finished_at,
                                  message_count, transcript_path,
                                  git_branch, forked_from, content_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    scope_cwd,
                    session_id,
                    source,
                    agent_uuid,
                    started_at,
                    finished_at,
                    message_count,
                    transcript_path,
                    git_branch,
                    forked_from,
                    content_hash,
                ),
            )
            print(cur.lastrowid)
        except sqlite3.IntegrityError:
            # duplicate content_hash — already imported
            print("")


def chat_set_summary(chat_id: int, summary: str) -> None:
    with conn() as c:
        c.execute("UPDATE chats SET summary=? WHERE id=?", (summary, chat_id))


def chat_list(project: str | None = None, limit: int = 30) -> None:
    with conn() as c:
        pid = _project_id(c, project)
        if pid is None:
            # show all
            rows = c.execute(
                """
                SELECT chats.id, COALESCE(projects.name,'(none)'),
                       session_id, source, started_at, finished_at,
                       message_count, COALESCE(summary,'')
                FROM chats LEFT JOIN projects ON projects.id = chats.project_id
                ORDER BY chats.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT id, '', session_id, source, started_at, finished_at,
                       message_count, COALESCE(summary,'')
                FROM chats WHERE project_id=? ORDER BY id DESC LIMIT ?
                """,
                (pid, limit),
            ).fetchall()
        for cid, pname, sid, src, started, finished, count, summary in reversed(rows):
            tag = f"[{pname}]  " if pname else ""
            print(
                f"#{cid:>4}  {tag}{sid[:8]}  {src:<22}  msgs={count or 0:<4}  "
                f"{started or '?'}  -- {summary}"
            )


def chat_show(chat_id: int) -> None:
    with conn() as c:
        row = c.execute(
            "SELECT transcript_path, session_id FROM chats WHERE id=?", (chat_id,)
        ).fetchone()
        if not row:
            sys.exit(f"no chat #{chat_id}")
        path, sid = row
        if not Path(path).exists():
            sys.exit(f"transcript missing: {path}")
        print(f"# chat #{chat_id}  session={sid}  path={path}")
        # If it's a Claude jsonl, render readably. If markdown, just cat.
        if path.endswith(".jsonl"):
            for line in Path(path).read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    import json
                    obj = json.loads(line)
                except Exception:
                    print(line)
                    continue
                t = obj.get("type") or obj.get("message", {}).get("role")
                ts = obj.get("timestamp", "")
                msg = obj.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                parts.append(item.get("text", ""))
                            elif item.get("type") == "tool_use":
                                parts.append(f"[tool_use:{item.get('name')}]")
                            elif item.get("type") == "tool_result":
                                parts.append("[tool_result]")
                        else:
                            parts.append(str(item))
                    content = " ".join(parts)
                if t in ("user", "assistant"):
                    print(f"\n--- {t} ({ts}) ---")
                    print(content[:2000])
        else:
            print(Path(path).read_text())


COMMANDS = {
    "init": lambda a: init(),
    "set-project": lambda a: set_project(a[0]),
    "active": lambda a: active(),
    "list-projects": lambda a: list_projects(),
    "add-todo": lambda a: add_todo(a[0], " ".join(a[1:])),
    "list-todos": lambda a: list_todos(a[0] if a else None),
    "done": lambda a: done_todo(int(a[0])),
    "edit-todo": lambda a: edit_todo(int(a[0]), " ".join(a[1:])),
    "add-script": lambda a: add_script(a[0], a[1], a[2], " ".join(a[3:])),
    "list-scripts": lambda a: list_scripts(a[0] if a else None),
    "log-action": lambda a: log_action(a[0] or None, a[1], a[2], " ".join(a[3:])),
    "show-log": lambda a: show_log(int(a[0]) if a else 20),
    "queue-add": lambda a: queue_add(a[0], " ".join(a[1:])),
    "queue-list": lambda a: queue_list(),
    "queue-pop": lambda a: queue_pop(int(a[0])),
    "queue-done": lambda a: queue_done(int(a[0])),
    "current-set": lambda a: current_set(a[0], int(a[1])),
    "current-show": lambda a: current_show(),
    "current-clear": lambda a: current_clear(),
    "set-project-path": lambda a: set_project_path(a[0], a[1]),
    "project-path": lambda a: project_path(a[0]),
    "meta-set": lambda a: meta_set(a[0], " ".join(a[1:])),
    "meta-get": lambda a: meta_get(a[0]),
    "meta-list": lambda a: meta_list(),
    "entry-add": lambda a: entry_add(a[0], a[1], a[2]),
    "entry-list": lambda a: entry_list(),
    "entry-clear": lambda a: entry_clear(),
    "run-add": lambda a: run_add(a[0], a[1], int(a[2]), a[3], a[4], a[5]),
    "run-list": lambda a: run_list(int(a[0]) if a else 20),
    "run-last-stderr": lambda a: run_last_stderr(int(a[0]) if a else 1),
    "agent-claim": lambda a: agent_claim(a[0], int(a[1]), a[2], " ".join(a[3:])),
    "agent-update": lambda a: agent_update(a[0], " ".join(a[1:])),
    "agent-release": lambda a: agent_release(a[0]),
    "agent-list": lambda a: agent_list(),
    "tool-def": lambda a: tool_def(a[0], a[1], a[2], a[3], a[4], a[5], a[6] if len(a) > 6 else ""),
    "tool-get": lambda a: tool_get(a[0]),
    "tool-list": lambda a: tool_list(),
    "tool-delete": lambda a: tool_delete(a[0]),
    "workflow-def": lambda a: workflow_def(a[0], a[1], a[2]),
    "workflow-get": lambda a: workflow_get(a[0]),
    "workflow-list": lambda a: workflow_list(),
    "workflow-used": lambda a: workflow_used(a[0]),
    "workflow-search": lambda a: workflow_search(" ".join(a)),
    "agent-def": lambda a: agent_def(a[0], a[1], a[2], " ".join(a[3:])),
    "agent-def-get": lambda a: agent_def_get(a[0]),
    "agent-def-list": lambda a: agent_def_list(),
    "agent-def-delete": lambda a: agent_def_delete(a[0]),
    "swarm-def": lambda a: swarm_def(a[0], a[1], a[2], a[3] if len(a) > 3 else "", int(a[4]) if len(a) > 4 else 10),
    "swarm-def-get": lambda a: swarm_def_get(a[0]),
    "swarm-def-list": lambda a: swarm_def_list(),
    "swarm-run-start": lambda a: swarm_run_start(a[0], a[1], a[2]),
    "swarm-run-step-add": lambda a: swarm_run_step_add(
        int(a[0]), int(a[1]), int(a[2]), a[3], a[4], a[5], int(a[6])
    ),
    "swarm-run-end": lambda a: swarm_run_end(int(a[0]), a[1], int(a[2])),
    "swarm-run-show": lambda a: swarm_run_show(int(a[0])),
    "swarm-run-last": lambda a: swarm_run_last(),
    "chain-run-start": lambda a: chain_run_start(a[0], a[1] if len(a) > 1 else ""),
    "chain-run-step-add": lambda a: chain_run_step_add(
        int(a[0]), int(a[1]), a[2], int(a[3]), a[4], a[5], a[6],
        int(a[7]), int(a[8]),
    ),
    "chain-run-end": lambda a: chain_run_end(int(a[0]), a[1]),
    "chain-run-show": lambda a: chain_run_show(int(a[0])),
    "chain-run-last": lambda a: chain_run_last(),
    "chain-run-list": lambda a: chain_run_list(int(a[0]) if a else 20),
    "card-upsert": lambda a: card_upsert(a[0], a[1], a[2], a[3] if len(a) > 3 else "tiny-chain"),
    "card-get": lambda a: card_get(a[0]),
    "card-list": lambda a: card_list(),
    "card-delete": lambda a: card_delete(a[0]),
    "gui-upsert": lambda a: gui_card_upsert(a[0], a[1], a[2], a[3] if len(a) > 3 else "tiny-chain"),
    "gui-get": lambda a: gui_card_get(a[0]),
    "gui-list": lambda a: gui_card_list(),
    "gui-delete": lambda a: gui_card_delete(a[0]),
    "template-add": lambda a: template_add(
        a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7],
        a[8] if len(a) > 8 else "",
    ),
    "template-list": lambda a: template_list(),
    "template-show": lambda a: template_show(a[0]),
    "template-delete": lambda a: template_delete(a[0]),
    "template-used": lambda a: template_used(a[0]),
    "job-start": lambda a: job_start(
        a[0], a[1], a[2] if len(a) > 2 else "{}",
        a[3] if len(a) > 3 else "",
    ),
    "job-set-status": lambda a: job_set_status(
        int(a[0]), a[1], int(a[2]) if len(a) > 2 else 0,
    ),
    "job-advance": lambda a: job_advance(
        int(a[0]), int(a[1]), a[2] if len(a) > 2 else "",
    ),
    "job-step-add": lambda a: job_step_add(
        int(a[0]), int(a[1]), a[2], a[3], a[4], a[5], a[6],
        a[7], a[8], a[9], int(a[10]),
    ),
    "job-show": lambda a: job_show(int(a[0])),
    "job-list": lambda a: job_list(int(a[0]) if a else 20),
    "job-last": lambda a: job_last(),
    "dag-node-upsert": lambda a: dag_node_upsert(
        a[0], a[1], a[2], a[3],
        a[4] if len(a) > 4 else "",
        a[5] if len(a) > 5 else "",
    ),
    "dag-edge-upsert": lambda a: dag_edge_upsert(
        a[0], a[1], a[2], a[3],
        float(a[4]) if len(a) > 4 else 1.0,
        a[5] if len(a) > 5 else "",
    ),
    "dag-chain-upsert": lambda a: dag_chain_upsert(
        a[0], a[1], a[2], a[3], float(a[4]),
        a[5] if len(a) > 5 else "",
        a[6] if len(a) > 6 else "",
    ),
    "dag-node-get": lambda a: dag_node_get(a[0]),
    "dag-chain-get": lambda a: dag_chain_get(a[0]),
    "dag-status": lambda a: dag_status(),
    "dag-queue-add": lambda a: dag_queue_add(
        a[0], a[1], int(a[2]) if len(a) > 2 else 0,
    ),
    "dag-queue-pop": lambda a: dag_queue_pop(),
    "dag-queue-complete": lambda a: dag_queue_complete(
        int(a[0]), a[1],
        int(a[2]) if len(a) > 2 else 0,
        a[3] if len(a) > 3 else "",
    ),
    "dag-mark-chain-stale": lambda a: dag_mark_chain_stale(a[0]),
    "dag-mark-node-stale": lambda a: dag_mark_node_stale(a[0]),
    "dag-chain-hit": lambda a: dag_chain_hit(a[0]),
    "dag-successors": lambda a: dag_successors(
        a[0], int(a[1]) if len(a) > 1 else 5,
    ),
    "dag-chains-from": lambda a: dag_chains_from(
        a[0], int(a[1]) if len(a) > 1 else 10,
    ),
    "dag-chains-pair": lambda a: dag_chains_pair(
        a[0], a[1], int(a[2]) if len(a) > 2 else 10,
    ),
    "phase-start": lambda a: phase_start(a[0], " ".join(a[1:])),
    "phase-active": lambda a: phase_active(a[0]),
    "phase-step-add": lambda a: phase_step_add(
        int(a[0]), a[1], a[2], a[3], int(a[4]), a[5]
    ),
    "phase-context": lambda a: phase_context(
        int(a[0]), int(a[1]) if len(a) > 1 else 10
    ),
    "phase-show": lambda a: phase_show(int(a[0])),
    "phase-end": lambda a: phase_end(int(a[0]), " ".join(a[1:])),
    "phase-list": lambda a: phase_list(a[0] if a and a[0] not in ("", "-") else None),
    "chat-exists-by-hash": lambda a: chat_exists_by_hash(a[0]),
    "chat-add": lambda a: chat_add(
        a[0], a[1], a[2], a[3], a[4], a[5], a[6], int(a[7]), a[8], a[9], a[10], a[11]
    ),
    "chat-set-summary": lambda a: chat_set_summary(int(a[0]), " ".join(a[1:])),
    "chat-list": lambda a: chat_list(
        a[0] if a and a[0] not in ("", "-") else None,
        int(a[1]) if len(a) > 1 else 30,
    ),
    "chat-show": lambda a: chat_show(int(a[0])),
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    fn = COMMANDS.get(cmd)
    if not fn:
        sys.exit(f"unknown subcommand: {cmd}")
    fn(rest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
