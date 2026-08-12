#!/usr/bin/env python3
import csv
import sqlite3
import sys
from pathlib import Path


def main(argv):
    if len(argv) != 3:
        print("usage: build_ecdict_sqlite.py INPUT_CSV OUTPUT_SQLITE", file=sys.stderr)
        return 2

    csv_path = Path(argv[1])
    db_path = Path(argv[2])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute(
            """
            CREATE TABLE entries (
                word TEXT PRIMARY KEY,
                phonetic TEXT,
                translation TEXT,
                definition TEXT,
                exchange TEXT
            )
            """
        )

        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = (
                (
                    (row.get("word") or "").strip().lower(),
                    (row.get("phonetic") or "").strip(),
                    (row.get("translation") or "").strip(),
                    (row.get("definition") or "").strip(),
                    (row.get("exchange") or "").strip(),
                )
                for row in reader
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO entries
                    (word, phonetic, translation, definition, exchange)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row for row in rows if row[0] and row[2]),
            )

        connection.execute("CREATE INDEX entries_word_idx ON entries(word)")
        connection.commit()
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
