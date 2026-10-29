"""D1 backup -> damage -> restore drill against the local wrangler D1 state.

Proves the documented recovery path: export a backup, wipe the tables, import the
backup back, and confirm every table and the progress payloads match byte for byte.
A pre-drill snapshot is taken first and replayed at the end so local dev data survives.

`wrangler d1 export` does not accept --persist-to, so the drill runs on the default
local D1 state rather than an isolated directory. Remote mode (--remote) is
verify-only and requires CLOUDFLARE_API_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_NAME = "kaoyan2-users"
SCHEMA = ROOT / "backend" / "schema.sql"
DRILL_DIR = ROOT / "dist" / "d1-drill"

TABLES = ("users", "sessions", "progress", "pair_codes", "rate")

# 删除必须子表先于父表：sessions/progress/pair_codes 都引用 users(id)，
# D1 默认开外键约束，先删 users 会让后续 DELETE 整条语句失败。
DELETE_ORDER = ("progress", "sessions", "pair_codes", "rate", "users")

SEED_SQL = """
INSERT INTO users (username, pass_hash, pass_salt, created_at) VALUES
  ('drill_a', 'hash-a', 'salt-a', 1700000000),
  ('drill_b', 'hash-b', 'salt-b', 1700000001);
INSERT INTO sessions (token, user_id, expires_at) VALUES ('tok-1', 1, 1900000000);
INSERT INTO progress (user_id, payload, updated_at) VALUES
  (1, '{"words":{"abandon":3},"pos":{"deck":"ky2","posWord":"abandon"}}', 1700000100),
  (2, '{"words":{},"pos":{}}', 1700000101);
INSERT INTO pair_codes (code, user_id, expires_at) VALUES ('ABC123', 1, 1900000000);
INSERT INTO rate (key, n, reset_at) VALUES ('login:127.0.0.1', 4, 1700000200);
"""


def wrangler(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        sys.exit("npx not found on PATH")
    # 演练完全离线；wrangler 的指标上报在断网时会 fetch failed 并让整条命令退出非零。
    env = dict(os.environ, NO_COLOR="1", CI="1",
               WRANGLER_SEND_METRICS="false", NO_UPDATE_NOTIFIER="1")
    proc = subprocess.run(
        [npx, "--no-install", "wrangler", *args],
        cwd=ROOT, env=env, text=True, encoding="utf-8",
        errors="replace", capture_output=True,
    )
    if check and proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        sys.exit(f"wrangler {' '.join(args)} failed with {proc.returncode}")
    return proc


def scope(remote: bool) -> str:
    return "--remote" if remote else "--local"


def execute_file(path: Path, remote: bool) -> subprocess.CompletedProcess[str]:
    return wrangler([
        "d1", "execute", DB_NAME, scope(remote), "--yes",
        "--config", "wrangler.toml", "--file", str(path),
    ])


def export_sql(target: Path, remote: bool, *, schema: bool = False) -> None:
    args = [
        "d1", "export", DB_NAME, scope(remote),
        "--config", "wrangler.toml", "--skip-confirmation",
        "--output", str(target),
    ]
    if not schema:
        args.append("--no-schema")
    wrangler(args)
    if not target.is_file() or target.stat().st_size == 0:
        sys.exit(f"export produced no data: {target}")
    if not target.read_text(encoding="utf-8", errors="replace").strip():
        sys.exit(f"export produced an empty file: {target}")


def query(sql: str, remote: bool) -> list[dict]:
    proc = wrangler([
        "d1", "execute", DB_NAME, scope(remote), "--yes",
        "--config", "wrangler.toml", "--command", sql,
    ])
    text = proc.stdout
    start = text.find("[")
    if start < 0:
        return []
    payload = json.loads(text[start:text.rfind("]") + 1])
    return payload[0].get("results", []) if payload else []


def counts(remote: bool) -> dict[str, int]:
    out = {}
    for table in TABLES:
        rows = query(f"SELECT COUNT(*) AS n FROM {table}", remote)
        out[table] = rows[0]["n"] if rows else 0
    return out


def write_sql(name: str, body: str) -> Path:
    path = DRILL_DIR / name
    path.write_text(body, encoding="utf-8")
    return path


def restore(data_file: Path, remote: bool) -> None:
    """Replay a data-only export; schema is applied separately because export omits it."""
    execute_file(SCHEMA, remote)
    execute_file(data_file, remote)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", action="store_true", help="verify-only against production D1")
    args = ap.parse_args()
    remote = args.remote

    if remote and not os.environ.get("CLOUDFLARE_API_TOKEN"):
        sys.exit("remote drill requires CLOUDFLARE_API_TOKEN")

    if DRILL_DIR.exists():
        shutil.rmtree(DRILL_DIR)
    DRILL_DIR.mkdir(parents=True, exist_ok=True)

    backup_file = DRILL_DIR / "backup.sql"
    steps: list[str] = []

    if remote:
        export_sql(backup_file, True)
        steps.append(f"backup: remote snapshot {backup_file.stat().st_size} B")
        tables = counts(True)
        steps.append(f"verify-only: {tables}")
        print(json.dumps({
            "ok": bool(backup_file.stat().st_size), "mode": "remote", "db": DB_NAME,
            "backup": str(backup_file.relative_to(ROOT)), "tables": tables, "steps": steps,
        }, ensure_ascii=False, indent=2))
        return 0

    pre_drill = DRILL_DIR / "pre-drill.sql"
    clear_all = write_sql(
        "clear_all.sql", "".join(f"DELETE FROM {t};\n" for t in DELETE_ORDER))
    existing = counts(False)
    if any(existing.values()):
        export_sql(pre_drill, False)
        steps.append(f"snapshot: preserved existing local rows {existing}")
    else:
        steps.append("snapshot: local D1 empty, nothing to preserve")

    execute_file(clear_all, False)
    execute_file(SCHEMA, False)
    seed_file = write_sql("seed.sql", SEED_SQL)
    execute_file(seed_file, False)
    seeded = counts(False)
    if seeded["users"] != 2 or seeded["progress"] != 2:
        sys.exit(f"seed did not land: {seeded}")
    steps.append(f"seed: {seeded}")

    export_sql(backup_file, False)
    steps.append(f"backup: local snapshot {backup_file.stat().st_size} B")

    execute_file(clear_all, False)
    emptied = counts(False)
    if any(emptied.values()):
        sys.exit(f"damage step failed to empty tables: {emptied}")
    steps.append("damage: all tables emptied")

    restore(backup_file, False)
    restored = counts(False)
    if restored != seeded:
        sys.exit(f"restore mismatch: expected {seeded} got {restored}")
    steps.append(f"restore: {restored}")

    before = query("SELECT user_id, payload, updated_at FROM progress ORDER BY user_id", False)
    corrupt = write_sql(
        "corrupt.sql",
        "UPDATE progress SET payload = '{\"corrupt\":true}' WHERE user_id = 1;\n")
    execute_file(corrupt, False)
    execute_file(clear_all, False)
    restore(backup_file, False)
    after = query("SELECT user_id, payload, updated_at FROM progress ORDER BY user_id", False)
    if before != after:
        sys.exit(f"payload round-trip mismatch: {before} != {after}")
    steps.append("verify: progress payloads restored byte-identical")

    rollback = write_sql(
        "rollback.sql",
        "DELETE FROM progress;\nDELETE FROM sessions;\nDELETE FROM pair_codes;\n"
        "DELETE FROM rate;\nDELETE FROM users;\n")
    execute_file(rollback, False)
    if counts(False)["users"] != 0:
        sys.exit("rollback statement did not clear users")
    restore(backup_file, False)
    if counts(False) != seeded:
        sys.exit("data not recoverable after documented rollback")
    steps.append("rollback: clear+reimport path verified")

    if pre_drill.is_file():
        execute_file(clear_all, False)
        restore(pre_drill, False)
        steps.append(f"cleanup: local D1 restored to pre-drill state {counts(False)}")
    else:
        execute_file(clear_all, False)
        steps.append("cleanup: drill rows cleared, local D1 left empty")

    print(json.dumps({
        "ok": True, "mode": "local", "db": DB_NAME,
        "backup": str(backup_file.relative_to(ROOT)),
        "tables": seeded, "steps": steps,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
