"""Back up and import a consistent SQLite snapshot into MySQL. Dry run by default."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, select
from app.config import DATA_DIR, get_settings
from app.database import TABLES, get_engine, metadata, mysql_url

ORDER = ("students", "mastery", "messages", "quizzes", "events", "assignments")


def snapshot(source, destination):
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError("Source SQLite database does not exist")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def load_rows(source):
    with sqlite3.connect(source) as conn:
        conn.row_factory = sqlite3.Row
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Source database integrity check failed")
        rows = {name: [dict(r) for r in conn.execute(f'SELECT * FROM "{name}"')] for name in ORDER}
    student_ids = {r["id"] for r in rows["students"]}
    usernames = [r["username"] for r in rows["students"] if r.get("username")]
    if len(set(usernames)) != len(usernames):
        raise ValueError("Source contains duplicate login names")
    for name in ORDER[1:]:
        if any(r["student_id"] not in student_ids for r in rows[name]):
            raise ValueError(f"Orphan student references in {name}")
    for name, columns in {
        "messages": ("citations",), "quizzes": ("payload",), "events": ("detail",),
    }.items():
        for row in rows[name]:
            for col in columns:
                if row[col]:
                    json.loads(row[col])
    return rows


def import_rows(engine, rows, *, apply=False, backup_dir=None):
    metadata.create_all(engine)
    report = {}
    with engine.connect().execution_options(isolation_level="SERIALIZABLE") as conn:
        transaction = conn.begin()
        try:
            before = {name: [dict(r) for r in conn.execute(
                select(TABLES[name]).with_for_update()
            ).mappings()] for name in ORDER}
            empty_demo = (
                len(before["students"]) == 1
                and before["students"][0]["id"] == "demo-student"
                and before["students"][0]["name"] == "同学"
                and all(not before[name] for name in ORDER[1:])
            )
            if apply and backup_dir:
                Path(backup_dir, "mysql-before.json").write_text(
                    json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            for name in ORDER:
                table = TABLES[name]
                pk = [c.name for c in table.primary_key]
                existing = {tuple(r[k] for k in pk): r for r in before[name]}
                inserted = skipped = updated = 0
                for row in rows[name]:
                    unknown = set(row) - set(table.c.keys())
                    if unknown:
                        raise ValueError(f"Unmapped source columns in {name}: {sorted(unknown)}")
                    key = tuple(row[k] for k in pk)
                    old = existing.get(key)
                    if old is not None:
                        if all(old.get(k) == v for k, v in row.items()):
                            skipped += 1
                            continue
                        if name == "students" and key == ("demo-student",) and empty_demo:
                            conn.execute(table.update().where(table.c.id == "demo-student").values(**row))
                            updated += 1
                            continue
                        raise ValueError(f"Conflicting primary key in {name}; no records overwritten")
                    conn.execute(table.insert().values(**row))
                    inserted += 1
                report[name] = {
                    "source": len(rows[name]), "before": len(before[name]),
                    "inserted": inserted, "unchanged": skipped, "updated": updated,
                    "after": len(before[name]) + inserted,
                }
                # Compare every imported column before committing, including original IDs and JSON.
                for row in rows[name]:
                    saved = conn.execute(select(table).where(and_(*(
                        table.c[k] == row[k] for k in pk
                    )))).mappings().one()
                    if any(saved[k] != v for k, v in row.items()):
                        raise ValueError(f"Content verification failed in {name}")
            if apply:
                transaction.commit()
            else:
                transaction.rollback()
        except Exception:
            transaction.rollback()
            raise
    return report


def migrate(source=None, *, apply=False):
    source = Path(source) if source else DATA_DIR / "offline" / "tutor.db"
    backups = DATA_DIR / "backups" / ("mysql-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    backups.mkdir(parents=True)
    source_snapshot = backups / "source.db"
    snapshot(source, source_snapshot)
    rows = load_rows(source_snapshot)
    engine = get_engine(mysql_url(get_settings()))
    report = import_rows(engine, rows, apply=apply, backup_dir=backups)
    document = {
        "applied": apply, "source": str(source.resolve()), "backup": str(backups),
        "tables": report, "note": "Imported offline records remain demonstration data.",
    }
    (backups / "report.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.source, apply=args.apply), indent=2))
    except Exception as exc:
        # Do not print connection strings, passwords, learner records or SQL parameters.
        print("Migration failed: " + type(exc).__name__)
        if isinstance(exc, (ValueError, FileNotFoundError)):
            print(str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
