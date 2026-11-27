"""Merge offline SQLite records into the initialized primary SQLite database."""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import DATA_DIR, get_settings

TABLES = ("students", "mastery", "messages", "quizzes", "events", "assignments")


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def migrate(source: Path, target: Path, *, dry_run: bool = False) -> dict:
    source, target = source.resolve(), target.resolve()
    if source == target:
        raise ValueError("源数据库与目标数据库不能是同一个文件")
    if not source.is_file():
        raise FileNotFoundError(f"未找到离线数据库: {source}")

    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as src:
        src.row_factory = sqlite3.Row
        source_tables = {r["name"] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        missing = set(TABLES) - source_tables
        if missing:
            raise ValueError(f"源库缺少表: {', '.join(sorted(missing))}")

        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target, timeout=30) as dst:
            dst.row_factory = sqlite3.Row
            target_tables = {r["name"] for r in dst.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            missing = set(TABLES) - target_tables
            if missing:
                raise ValueError(
                    f"目标库未初始化，缺少表: {', '.join(sorted(missing))}。"
                    "请先启动一次正式模式服务。"
                )

            counts = {
                table: {
                    "target_before": dst.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                    "source": src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                }
                for table in TABLES
            }
            if dry_run:
                return {"dry_run": True, "tables": counts, "backup": None}

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = target.with_name(f"{target.stem}.before-migration-{stamp}{target.suffix}")
            with sqlite3.connect(backup_path) as backup:
                dst.backup(backup)

            try:
                dst.execute("BEGIN IMMEDIATE")
                src_student_cols = _columns(src, "students")
                dst_student_cols = set(_columns(dst, "students"))
                student_cols = [c for c in src_student_cols if c in dst_student_cols]
                dest_students = {
                    r["id"]: dict(r) for r in dst.execute("SELECT * FROM students")
                }

                for row in src.execute("SELECT * FROM students"):
                    student = dict(row)
                    existing = dest_students.get(student["id"])
                    if existing:
                        if student["id"] == "demo-student":
                            updates = [c for c in student_cols if c != "id"]
                            dst.execute(
                                "UPDATE students SET " + ", ".join(f'"{c}"=?' for c in updates) + " WHERE id=?",
                                tuple(student[c] for c in updates) + (student["id"],),
                            )
                        continue
                    username = student.get("username")
                    if username and dst.execute(
                        "SELECT 1 FROM students WHERE username=?", (username,)
                    ).fetchone():
                        base, suffix = username, 1
                        while dst.execute(
                            "SELECT 1 FROM students WHERE username=?", (f"{base}_{suffix}",)
                        ).fetchone():
                            suffix += 1
                        student["username"] = f"{base}_{suffix}"
                    columns = [c for c in student_cols if c in student]
                    dst.execute(
                        "INSERT INTO students (" + ", ".join(f'"{c}"' for c in columns) + ") VALUES (" +
                        ", ".join("?" for _ in columns) + ")",
                        tuple(student[c] for c in columns),
                    )

                for table in TABLES[1:]:
                    source_cols = _columns(src, table)
                    target_cols = set(_columns(dst, table))
                    columns = [c for c in source_cols if c in target_cols]
                    names = ", ".join(f'"{c}"' for c in columns)
                    marks = ", ".join("?" for _ in columns)
                    for row in src.execute(f'SELECT * FROM "{table}"'):
                        dst.execute(
                            f'INSERT OR IGNORE INTO "{table}" ({names}) VALUES ({marks})',
                            tuple(row[c] for c in columns),
                        )
                dst.commit()
            except Exception:
                dst.rollback()
                backup_path.unlink(missing_ok=True)
                raise

            for table in TABLES:
                counts[table]["target_after"] = dst.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
            return {"dry_run": False, "tables": counts, "backup": str(backup_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DATA_DIR / "offline" / "tutor.db")
    parser.add_argument("--target", type=Path, default=get_settings().db_path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate(args.source, args.target, dry_run=args.dry_run)
    for table, counts in result["tables"].items():
        print(f"{table}: {counts}")
    if result["backup"]:
        print(f"目标库备份: {result['backup']}")
    print("预览完成，未修改数据库。" if result["dry_run"] else
          "迁移完成；离线源库保留未修改。")


if __name__ == "__main__":
    main()
