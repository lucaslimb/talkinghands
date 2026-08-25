"""Local score persistence and ranking queries for Talking Hands games."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings


SCORE_GAMES = ("piano_tiles", "genius_drums")
SCORES_DB_PATH = Path(settings.RECORDINGS_ROOT) / "scores.sqlite3"


def _connect() -> sqlite3.Connection:
    SCORES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SCORES_DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS game_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_key TEXT NOT NULL,
            nickname TEXT NOT NULL COLLATE NOCASE,
            score INTEGER NOT NULL,
            difficulty TEXT NOT NULL,
            song TEXT,
            precision INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(game_scores)")}
    if "precision" not in columns:
        connection.execute("ALTER TABLE game_scores ADD COLUMN precision INTEGER")
        connection.commit()
    return connection


def save_game_score(
    game_key: str,
    nickname: str,
    score: int,
    difficulty: str,
    song: str | None = None,
    precision: int | None = None,
) -> bool:
    """Persist one completed attempt. Rankings aggregate each user's best score."""
    clean_name = " ".join(str(nickname).split())[:24]
    if game_key not in SCORE_GAMES or not clean_name:
        return False

    connection = None
    try:
        connection = _connect()
        connection.execute(
            """
            INSERT INTO game_scores (game_key, nickname, score, difficulty, song, precision, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_key,
                clean_name,
                max(0, int(score)),
                str(difficulty),
                song or None,
                None if precision is None else max(0, min(100, int(precision))),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        connection.commit()
        print(f"[scores] saved game={game_key!r} nickname={clean_name!r} score={score}")
        return True
    except (OSError, sqlite3.Error) as exc:
        print(f"[scores] save failed: {exc}")
        return False
    finally:
        if connection is not None:
            connection.close()


def get_ranking(
    game_key: str,
    difficulty: str | None = None,
    song: str | None = None,
    limit: int = 10,
) -> list[tuple[str, int, str, str | None, int | None]]:
    """Return each nickname's best filtered attempt with its ranking metadata."""
    if game_key not in SCORE_GAMES:
        return []
    connection = None
    try:
        connection = _connect()
        filters = ["game_key = ?"]
        values: list[object] = [game_key]
        if difficulty:
            filters.append("difficulty = ?")
            values.append(difficulty)
        if song:
            filters.append("song = ?")
            values.append(song)
        where_clause = " AND ".join(filters)
        rows = connection.execute(
            f"""
            SELECT nickname, score, difficulty, song, precision
            FROM game_scores AS attempt
            WHERE {where_clause}
              AND id = (
                  SELECT id
                  FROM game_scores AS best_attempt
                  WHERE best_attempt.nickname = attempt.nickname COLLATE NOCASE
                    AND {where_clause.replace('game_key', 'best_attempt.game_key').replace('difficulty', 'best_attempt.difficulty').replace('song', 'best_attempt.song')}
                  ORDER BY score DESC, id ASC
                  LIMIT 1
              )
            ORDER BY score DESC, nickname COLLATE NOCASE ASC
            LIMIT ?
            """,
            tuple(values + values + [max(1, int(limit))]),
        ).fetchall()
        return [
            (str(nickname), int(score), str(row_difficulty), row_song,
             None if precision is None else int(precision))
            for nickname, score, row_difficulty, row_song, precision in rows
        ]
    except (OSError, sqlite3.Error) as exc:
        print(f"[scores] ranking query failed: {exc}")
        return []
    finally:
        if connection is not None:
            connection.close()
