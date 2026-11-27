import json
import re
import sqlite3
import threading
from collections import Counter
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from core.sentence_splitter import split_chinese_text, clean_chinese_text, is_junk_text

DB_PATH = Path("data/dub_studio.db")


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # បើ Database មិនទាន់មាន ចម្លង Template ស្រាប់ដែលមានពាក្យ 2,167+ រួចជាស្រេចភ្លាមៗ (0.002s)
        if not self.db_path.exists():
            import shutil
            import sys
            base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
            for candidate in (
                base_dir / "assets" / "default_db" / "dub_studio.db",
                base_dir / "assets" / "default_db" / "aisummarai.db",
                base_dir / "data" / "aisummarai.db",
            ):
                if candidate.exists() and candidate.stat().st_size > 10000:
                    try:
                        shutil.copy2(candidate, self.db_path)
                        break
                    except Exception:
                        pass
        self._lock = threading.RLock()
        self._local = threading.local()
        with self._lock:
            conn = self.conn
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute("PRAGMA busy_timeout = 60000;")
            except Exception:
                pass
            self._init_tables()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=60.0,
                cached_statements=0,
            )
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute("PRAGMA busy_timeout = 60000;")
            except Exception:
                pass
            self._local.conn = conn
        return conn

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _init_tables(self):
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    source_mode TEXT NOT NULL,
                    kh_voice TEXT DEFAULT 'km-KH-SreymomNeural',
                    keep_bgm INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    seq_index INTEGER NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    zh_text TEXT DEFAULT '',
                    kh_text TEXT DEFAULT '',
                    voice_override TEXT DEFAULT '',
                    tts_audio_path TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    bbox_json TEXT DEFAULT '',
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_edits (
                    project_id INTEGER PRIMARY KEY,
                    logo_path TEXT DEFAULT '',
                    logo_x REAL DEFAULT 0.05,
                    logo_y REAL DEFAULT 0.05,
                    logo_scale REAL DEFAULT 0.15,
                    logo_opacity REAL DEFAULT 0.90,
                    burn_subs INTEGER DEFAULT 0,
                    sub_y REAL DEFAULT 0.85,
                    sub_font_size INTEGER DEFAULT 24,
                    sub_font_family TEXT DEFAULT '',
                    sub_color TEXT DEFAULT '#FFFFFF',
                    sub_bg INTEGER DEFAULT 1,
                    brightness REAL DEFAULT 0.0,
                    contrast REAL DEFAULT 1.0,
                    saturation REAL DEFAULT 1.0,
                    trim_start_ms INTEGER DEFAULT 0,
                    trim_end_ms INTEGER DEFAULT 0,
                    aspect_ratio TEXT DEFAULT 'original',
                    mask_enabled INTEGER DEFAULT 0,
                    mask_mode TEXT DEFAULT 'blur',
                    mask_x REAL DEFAULT 0.05,
                    mask_y REAL DEFAULT 0.78,
                    mask_w REAL DEFAULT 0.90,
                    mask_h REAL DEFAULT 0.14,
                    mask_strength REAL DEFAULT 0.75,
                    mask_color TEXT DEFAULT '#000000',
                    anti_copyright_enabled INTEGER DEFAULT 1,
                    anti_copyright_level TEXT DEFAULT 'medium',
                    anti_copyright_flip INTEGER DEFAULT 0,
                    anti_copyright_border INTEGER DEFAULT 0,
                    auto_blur_chinese INTEGER DEFAULT 1,
                    auto_timed_blur INTEGER DEFAULT 1,
                    lut_preset TEXT DEFAULT 'none',
                    mute_original_audio INTEGER DEFAULT 1,
                    keep_bgm_only INTEGER DEFAULT 0,
                    hook_enabled INTEGER DEFAULT 0,
                    hook_text TEXT DEFAULT '',
                    hook_pos TEXT DEFAULT 'top',
                    hook_bg_color TEXT DEFAULT '#D90429',
                    hook_text_color TEXT DEFAULT '#FFFFFF',
                    hook_height_pct INTEGER DEFAULT 12,
                    hook_font_size INTEGER DEFAULT 28,
                    intro_enabled INTEGER DEFAULT 0,
                    intro_path TEXT DEFAULT '',
                    outro_enabled INTEGER DEFAULT 0,
                    outro_path TEXT DEFAULT '',
                    series_profile_id INTEGER DEFAULT 0,
                    hd_upscale_enabled INTEGER DEFAULT 0,
                    hd_upscale_1080p INTEGER DEFAULT 0,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
            """)
            # បន្ថែម Column ថ្មីដោយស្វ័យប្រវត្តិសម្រាប់ Database ចាស់ៗ (Segments + Project Edits Full Migration)
            try:
                seg_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(segments)").fetchall()}
                seg_migrations = [
                    ("zh_text", "TEXT DEFAULT ''"),
                    ("kh_text", "TEXT DEFAULT ''"),
                    ("voice_override", "TEXT DEFAULT ''"),
                    ("tts_audio_path", "TEXT DEFAULT ''"),
                    ("status", "TEXT DEFAULT 'pending'"),
                    ("bbox_json", "TEXT DEFAULT ''"),
                ]
                for sc_name, sc_def in seg_migrations:
                    if sc_name not in seg_cols:
                        self.conn.execute(f"ALTER TABLE segments ADD COLUMN {sc_name} {sc_def}")
            except Exception:
                pass

            new_cols = [
                ("logo_path", "TEXT DEFAULT ''"),
                ("logo_x", "REAL DEFAULT 0.05"),
                ("logo_y", "REAL DEFAULT 0.05"),
                ("logo_scale", "REAL DEFAULT 0.15"),
                ("logo_opacity", "REAL DEFAULT 0.90"),
                ("burn_subs", "INTEGER DEFAULT 0"),
                ("sub_y", "REAL DEFAULT 0.85"),
                ("sub_font_size", "INTEGER DEFAULT 24"),
                ("sub_color", "TEXT DEFAULT '#FFFFFF'"),
                ("sub_bg", "INTEGER DEFAULT 1"),
                ("brightness", "REAL DEFAULT 0.0"),
                ("contrast", "REAL DEFAULT 1.0"),
                ("saturation", "REAL DEFAULT 1.0"),
                ("trim_start_ms", "INTEGER DEFAULT 0"),
                ("trim_end_ms", "INTEGER DEFAULT 0"),
                ("aspect_ratio", "TEXT DEFAULT 'original'"),
                ("mask_enabled", "INTEGER DEFAULT 0"),
                ("mask_mode", "TEXT DEFAULT 'blur'"),
                ("mask_x", "REAL DEFAULT 0.05"),
                ("mask_y", "REAL DEFAULT 0.78"),
                ("mask_w", "REAL DEFAULT 0.90"),
                ("mask_h", "REAL DEFAULT 0.14"),
                ("mask_strength", "REAL DEFAULT 0.75"),
                ("mask_color", "TEXT DEFAULT '#000000'"),
                ("custom_bgm_path", "TEXT DEFAULT ''"),
                ("custom_bgm_vol", "REAL DEFAULT 0.18"),
                ("auto_ducking", "INTEGER DEFAULT 1"),
                ("sub_style", "TEXT DEFAULT 'classic_box'"),
                ("sub_font_family", "TEXT DEFAULT ''"),
                ("masks_json", "TEXT DEFAULT '[]'"),
                ("dub_volume", "REAL DEFAULT 1.0"),
                ("anti_copyright_enabled", "INTEGER DEFAULT 1"),
                ("anti_copyright_level", "TEXT DEFAULT 'medium'"),
                ("anti_copyright_flip", "INTEGER DEFAULT 0"),
                ("anti_copyright_border", "INTEGER DEFAULT 0"),
                ("auto_blur_chinese", "INTEGER DEFAULT 1"),
                ("auto_timed_blur", "INTEGER DEFAULT 1"),
                ("lut_preset", "TEXT DEFAULT 'none'"),
                ("mute_original_audio", "INTEGER DEFAULT 1"),
                ("keep_bgm_only", "INTEGER DEFAULT 0"),
                ("hook_enabled", "INTEGER DEFAULT 0"),
                ("hook_text", "TEXT DEFAULT ''"),
                ("hook_pos", "TEXT DEFAULT 'top'"),
                ("hook_bg_color", "TEXT DEFAULT '#D90429'"),
                ("hook_text_color", "TEXT DEFAULT '#FFFFFF'"),
                ("hook_height_pct", "INTEGER DEFAULT 12"),
                ("hook_font_size", "INTEGER DEFAULT 28"),
                ("intro_enabled", "INTEGER DEFAULT 0"),
                ("intro_path", "TEXT DEFAULT ''"),
                ("outro_enabled", "INTEGER DEFAULT 0"),
                ("outro_path", "TEXT DEFAULT ''"),
                ("series_profile_id", "INTEGER DEFAULT 0"),
                ("hd_upscale_enabled", "INTEGER DEFAULT 0"),
                ("hd_upscale_1080p", "INTEGER DEFAULT 0"),
            ]
            for col_name, col_def in new_cols:
                try:
                    self.conn.execute(f"ALTER TABLE project_edits ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS glossary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    src_term TEXT UNIQUE NOT NULL,
                    kh_term TEXT NOT NULL,
                    category TEXT DEFAULT 'general'
                );
                CREATE INDEX IF NOT EXISTS idx_segments_proj_time ON segments(project_id, start_ms);
                CREATE INDEX IF NOT EXISTS idx_glossary_src ON glossary(src_term);

                CREATE TABLE IF NOT EXISTS sfx_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    audio_path TEXT NOT NULL,
                    volume REAL DEFAULT 0.85
                );
                CREATE INDEX IF NOT EXISTS idx_sfx_proj ON sfx_events(project_id, start_ms);

                CREATE TABLE IF NOT EXISTS studio_presets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    config_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS series_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_name TEXT UNIQUE NOT NULL,
                    default_voice_map_json TEXT DEFAULT '{}',
                    glossary_json TEXT DEFAULT '[]',
                    edits_preset_json TEXT DEFAULT '{}',
                    intro_path TEXT DEFAULT '',
                    outro_path TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS cloned_voices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    sample_path TEXT DEFAULT '',
                    gender TEXT DEFAULT 'female',
                    base_voice TEXT DEFAULT 'km-KH-SreymomNeural',
                    pitch_shift INTEGER DEFAULT 0,
                    formant_shift REAL DEFAULT 1.0,
                    warmth REAL DEFAULT 1.2,
                    brightness REAL DEFAULT 1.1,
                    tempo_rate REAL DEFAULT 1.0,
                    voice_color TEXT DEFAULT 'natural',
                    fx TEXT DEFAULT '',
                    api_voice_id TEXT DEFAULT '',
                    is_preset INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Migration check for category column in glossary
            try:
                cur_cols = [r[1] for r in self.conn.execute("PRAGMA table_info(glossary)").fetchall()]
                if "category" not in cur_cols:
                    self.conn.execute("ALTER TABLE glossary ADD COLUMN category TEXT DEFAULT 'general'")
            except Exception:
                pass

            # Seed 2,000+ Spoken Khmer Dubbing Glossary Pack if empty or below 1,500 terms
            try:
                cnt = self.conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0]
                if cnt < 1500:
                    from core.khmer_dub_glossary_dataset import SPOKEN_KHMER_GLOSSARY_PACK
                    with self.conn:
                        self.conn.executemany(
                            """INSERT OR REPLACE INTO glossary (src_term, kh_term, category) VALUES (?, ?, ?)""",
                            SPOKEN_KHMER_GLOSSARY_PACK,
                        )
            except Exception as e:
                print(f"[Glossary Seed Error] {e}")

    def set_setting(self, key: str, value: str):
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(key), str(value)),
                    )
                finally:
                    cur.close()

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT value FROM settings WHERE key=?", (str(key),))
                row = cur.fetchone()
                return str(row["value"]) if row else str(default)
            finally:
                cur.close()

    def get_api_keys(self) -> List[str]:
        """Returns all configured Gemini/OpenAI API keys (1 per line) stored in SQLite settings."""
        raw = self.get_setting("api_key", "")
        if not raw:
            return []
        tokens = [t.strip() for t in re.split(r"[\r\n,;]+", raw) if t.strip()]
        seen = set()
        out = []
        for k in tokens:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def set_api_keys(self, keys: List[str] | str) -> int:
        """Persists a list or multi-line string of API keys cleanly into SQLite."""
        if isinstance(keys, str):
            tokens = [t.strip() for t in re.split(r"[\r\n,;]+", keys) if t.strip()]
        else:
            tokens = [str(k).strip() for k in (keys or []) if str(k).strip()]
        seen = set()
        clean = []
        for k in tokens:
            if k not in seen:
                seen.add(k)
                clean.append(k)
        self.set_setting("api_key", "\n".join(clean))
        return len(clean)

    def create_project(self, name: str, video_path: str, source_mode: str) -> int:
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute(
                        "INSERT INTO projects (name, video_path, source_mode) VALUES (?, ?, ?)",
                        (name, video_path, source_mode),
                    )
                    return cur.lastrowid
                finally:
                    cur.close()

    def list_projects(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT p.id, p.name, p.video_path, p.source_mode, p.created_at,
                           COUNT(s.id) AS line_count
                    FROM projects p
                    LEFT JOIN segments s ON s.project_id = p.id
                    GROUP BY p.id
                    ORDER BY p.created_at DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            finally:
                cur.close()

    def delete_project(self, project_id: int):
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute("DELETE FROM segments WHERE project_id=?", (int(project_id),))
                    cur.execute("DELETE FROM project_edits WHERE project_id=?", (int(project_id),))
                    cur.execute("DELETE FROM sfx_events WHERE project_id=?", (int(project_id),))
                    cur.execute("DELETE FROM projects WHERE id=?", (int(project_id),))
                finally:
                    cur.close()

    def get_project_edits(self, project_id: int) -> Dict[str, Any]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT * FROM project_edits WHERE project_id=?", (int(project_id),))
                row = cur.fetchone()
                if not row:
                    with self.conn:
                        cur.execute("INSERT INTO project_edits (project_id) VALUES (?)", (int(project_id),))
                    cur.execute("SELECT * FROM project_edits WHERE project_id=?", (int(project_id),))
                    row = cur.fetchone()
                res = dict(row) if row else {}
                if "anti_copyright_enabled" not in res or res["anti_copyright_enabled"] is None:
                    res["anti_copyright_enabled"] = 1
                if "auto_blur_chinese" not in res or res["auto_blur_chinese"] is None:
                    res["auto_blur_chinese"] = 1
                if "auto_timed_blur" not in res or res["auto_timed_blur"] is None:
                    res["auto_timed_blur"] = 1
                if "lut_preset" not in res or res["lut_preset"] is None:
                    res["lut_preset"] = "none"
                if "sub_font_family" not in res or res["sub_font_family"] is None:
                    res["sub_font_family"] = ""
                if "mute_original_audio" not in res or res["mute_original_audio"] is None:
                    res["mute_original_audio"] = 1
                if "keep_bgm_only" not in res or res["keep_bgm_only"] is None:
                    res["keep_bgm_only"] = 0
                if "hook_enabled" not in res or res["hook_enabled"] is None:
                    res["hook_enabled"] = 0
                if "hook_text" not in res or res["hook_text"] is None:
                    res["hook_text"] = ""
                if "hook_pos" not in res or res["hook_pos"] is None:
                    res["hook_pos"] = "top"
                if "hook_bg_color" not in res or res["hook_bg_color"] is None:
                    res["hook_bg_color"] = "#D90429"
                if "hook_text_color" not in res or res["hook_text_color"] is None:
                    res["hook_text_color"] = "#FFFFFF"
                if "hook_height_pct" not in res or res["hook_height_pct"] is None:
                    res["hook_height_pct"] = 12
                if "hook_font_size" not in res or res["hook_font_size"] is None:
                    res["hook_font_size"] = 28
                if "intro_enabled" not in res or res["intro_enabled"] is None:
                    res["intro_enabled"] = 0
                if "intro_path" not in res or res["intro_path"] is None:
                    res["intro_path"] = ""
                if "outro_enabled" not in res or res["outro_enabled"] is None:
                    res["outro_enabled"] = 0
                if "outro_path" not in res or res["outro_path"] is None:
                    res["outro_path"] = ""
                if "series_profile_id" not in res or res["series_profile_id"] is None:
                    res["series_profile_id"] = 0
                if "hd_upscale_enabled" not in res or res["hd_upscale_enabled"] is None:
                    res["hd_upscale_enabled"] = 0
                if "hd_upscale_1080p" not in res or res["hd_upscale_1080p"] is None:
                    res["hd_upscale_1080p"] = 0
                return res
            finally:
                cur.close()

    def update_project_edits(self, project_id: int, edits_dict: dict = None, **fields):
        data = {}
        if edits_dict and isinstance(edits_dict, dict):
            data.update(edits_dict)
        if fields:
            data.update(fields)
        data.pop("project_id", None)
        if not data:
            return
        with self._lock:
            self.get_project_edits(project_id)  # Ensure row exists
            try:
                valid_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(project_edits)").fetchall()}
            except Exception:
                valid_cols = set()
            safe_data = {k: v for k, v in data.items() if not valid_cols or k in valid_cols}
            if not safe_data:
                return
            cols = ", ".join(f"{k}=?" for k in safe_data)
            vals = list(safe_data.values()) + [int(project_id)]
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute(f"UPDATE project_edits SET {cols} WHERE project_id=?", vals)
                finally:
                    cur.close()

    def insert_segments(self, project_id: int, items: List[Dict[str, Any]]):
        with self._lock:
            with self.conn:
                self.conn.execute("DELETE FROM segments WHERE project_id=?", (project_id,))
                self.conn.executemany(
                    """INSERT INTO segments (
                           project_id, seq_index, start_ms, end_ms,
                           zh_text, kh_text, voice_override, status, bbox_json
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            project_id,
                            idx,
                            item.get("start_ms", 0),
                            item.get("end_ms", 0),
                            item.get("zh_text", ""),
                            item.get("kh_text", ""),
                            item.get("voice_override", ""),
                            item.get("status", "pending"),
                            item.get("bbox_json", ""),
                        )
                        for idx, item in enumerate(items, start=1)
                    ],
                )

    def append_segments(self, project_id: int, items: List[Dict[str, Any]]):
        """Append new segments into an existing project without deleting existing ones"""
        if not items:
            return
        with self._lock:
            with self.conn:
                max_seq = self.conn.execute(
                    "SELECT COALESCE(MAX(seq_index), 0) FROM segments WHERE project_id=?",
                    (project_id,)
                ).fetchone()[0]
                self.conn.executemany(
                    """INSERT INTO segments (
                           project_id, seq_index, start_ms, end_ms,
                           zh_text, kh_text, voice_override, status, tts_audio_path, bbox_json
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            project_id,
                            max_seq + idx,
                            item.get("start_ms", 0),
                            item.get("end_ms", 0),
                            item.get("zh_text", ""),
                            item.get("kh_text", ""),
                            item.get("voice_override", ""),
                            item.get("status", "pending"),
                            item.get("tts_audio_path", ""),
                            item.get("bbox_json", ""),
                        )
                        for idx, item in enumerate(items, start=1)
                    ],
                )

    def add_single_segment(
        self,
        project_id: int,
        start_ms: int,
        end_ms: int,
        zh_text: str = "",
        kh_text: str = "",
        voice_override: str = "",
        status: str = "Ready",
    ) -> int:
        """Add a single segment at specific start/end timestamps"""
        with self._lock:
            with self.conn:
                max_seq = self.conn.execute(
                    "SELECT COALESCE(MAX(seq_index), 0) FROM segments WHERE project_id=?",
                    (project_id,)
                ).fetchone()[0]
                cur = self.conn.execute(
                    """INSERT INTO segments (
                           project_id, seq_index, start_ms, end_ms,
                           zh_text, kh_text, voice_override, status
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (project_id, max_seq + 1, start_ms, end_ms, zh_text, kh_text, voice_override, status),
                )
                return cur.lastrowid

    def get_segments(self, project_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    "SELECT * FROM segments WHERE project_id=? ORDER BY start_ms ASC, seq_index ASC, id ASC",
                    (int(project_id),),
                )
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            finally:
                cur.close()

    def get_segment_by_id(self, seg_id: int) -> Dict[str, Any] | None:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT * FROM segments WHERE id=?", (int(seg_id),))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                cur.close()

    def update_segment(self, seg_id: int, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [int(v) if isinstance(v, bool) else (str(v) if v is not None and not isinstance(v, (int, float)) else v) for v in fields.values()]
        vals.append(int(seg_id))
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute(f"UPDATE segments SET {cols} WHERE id=?", vals)
                finally:
                    cur.close()

    def delete_segments(self, seg_ids: List[int]):
        if not seg_ids:
            return
        clean_ids = [int(x) for x in seg_ids]
        placeholders = ",".join("?" for _ in clean_ids)
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute(f"DELETE FROM segments WHERE id IN ({placeholders})", clean_ids)
                finally:
                    cur.close()

    def merge_segments(self, seg_ids: List[int]) -> int:
        """Merges 2 or more consecutive rows into the first selected row."""
        if len(seg_ids) < 2:
            return 0
        placeholders = ",".join("?" for _ in seg_ids)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM segments WHERE id IN ({placeholders}) ORDER BY start_ms ASC",
                seg_ids,
            ).fetchall()
            if len(rows) < 2:
                return 0
            first = dict(rows[0])
            new_end = max(int(r["end_ms"]) for r in rows)
            merged_zh = " ".join((r["zh_text"] or "").strip() for r in rows if (r["zh_text"] or "").strip())
            merged_kh = " ".join((r["kh_text"] or "").strip() for r in rows if (r["kh_text"] or "").strip())

            del_ids = [int(r["id"]) for r in rows[1:]]
            del_placeholders = ",".join("?" for _ in del_ids)

            with self.conn:
                self.conn.execute(
                    "UPDATE segments SET end_ms=?, zh_text=?, kh_text=?, tts_audio_path='', status='Edited' WHERE id=?",
                    (new_end, merged_zh, merged_kh, first["id"]),
                )
                self.conn.execute(
                    f"DELETE FROM segments WHERE id IN ({del_placeholders})",
                    del_ids,
                )
            return len(del_ids)

    def get_glossary(self, category: str = None, search: str = None) -> List[Dict[str, Any]]:
        with self._lock:
            query = "SELECT id, src_term, kh_term, COALESCE(category, 'general') AS category FROM glossary WHERE 1=1"
            params = []
            if category and category not in ("all", "all_terms", ""):
                query += " AND category = ?"
                params.append(category)
            if search and search.strip():
                query += " AND (src_term LIKE ? OR kh_term LIKE ?)"
                kw = f"%{search.strip()}%"
                params.extend([kw, kw])
            query += " ORDER BY id DESC"
            rows = self.conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_glossary_count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM glossary").fetchone()
            return int(row[0]) if row else 0

    def upsert_glossary(self, zh_term: str, kh_term: str, category: str = "general"):
        zh = (zh_term or "").strip()
        kh = (kh_term or "").strip()
        cat = (category or "general").strip()
        if not zh or not kh:
            return
        with self._lock:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO glossary (src_term, kh_term, category) VALUES (?, ?, ?)
                       ON CONFLICT(src_term) DO UPDATE SET kh_term=excluded.kh_term, category=excluded.category""",
                    (zh, kh, cat),
                )

    def bulk_upsert_glossary(self, items: List[Tuple[str, str, str]]) -> int:
        """Loads and upserts a list of (zh_term, kh_term, category) tuples into glossary efficiently."""
        if not items:
            return 0
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                cur.executemany(
                    """INSERT INTO glossary (src_term, kh_term, category) VALUES (?, ?, ?)
                       ON CONFLICT(src_term) DO UPDATE SET kh_term=excluded.kh_term, category=excluded.category""",
                    items,
                )
                return cur.rowcount

    def delete_glossary(self, item_id: int):
        with self._lock:
            with self.conn:
                self.conn.execute("DELETE FROM glossary WHERE id=?", (item_id,))

    def set_glossary_items(self, items: List[Dict[str, str]]):
        with self._lock:
            with self.conn:
                self.conn.execute("DELETE FROM glossary")
                self.conn.executemany(
                    "INSERT OR IGNORE INTO glossary (src_term, kh_term, category) VALUES (?, ?, ?)",
                    [
                        (
                            i["src_term"].strip(),
                            i["kh_term"].strip(),
                            i.get("category", "general"),
                        )
                        for i in items
                        if i.get("src_term") and i.get("kh_term")
                    ],
                )

    def add_sfx_event(self, project_id: int, name: str, start_ms: int, audio_path: str, volume: float = 0.85) -> int:
        with self._lock:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO sfx_events(project_id, name, start_ms, audio_path, volume) VALUES(?, ?, ?, ?, ?)",
                    (project_id, name, start_ms, audio_path, volume),
                )
                return cur.lastrowid

    def get_sfx_events(self, project_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, project_id, name, start_ms, audio_path, volume FROM sfx_events WHERE project_id=? ORDER BY start_ms ASC",
                (project_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def delete_sfx_event(self, sfx_id: int):
        with self._lock:
            with self.conn:
                self.conn.execute("DELETE FROM sfx_events WHERE id=?", (sfx_id,))

    def clean_noise_segments(self, project_id: int) -> int:
        """
        លុបបន្ទាត់អក្សរសំរាម (Watermark ដដែលៗ, លេខ/សញ្ញាសុទ្ធ, ឬប្លង់ខ្លីក្រោម 150ms)
        ហើយត្រឡប់មកវិញនូវចំនួនជួរដែលបានលុប។
        """
        with self._lock:
            segs = self.get_segments(project_id)
            if not segs:
                return 0

            # រាប់ចំនួនដងដែលអក្សរដូចគ្នាបេះបិទលេចឡើង (Watermark ជាប់អេក្រង់ច្រើនតែលោត >= 4 ដង)
            normalized_list = [re.sub(r"\s+", "", (s.get("zh_text") or "")) for s in segs]
            freq = Counter(t for t in normalized_list if t)

            to_delete = []
            for seg, norm_txt in zip(segs, normalized_list):
                dur_ms = int(seg["end_ms"]) - int(seg["start_ms"])
                raw_txt = (seg.get("zh_text") or "").strip()

                # ១. លុបប្លង់ខ្លីពេក (< 150ms)
                if dur_ms < 150:
                    to_delete.append(seg["id"])
                    continue

                # ២. លុបជួរដែលមានតែលេខ សញ្ញា @ # ឬគ្មានតួអក្សរចិន/អង់គ្លេស/ខ្មែរ
                has_real_word = bool(re.search(r"[\u4e00-\u9fff\u1780-\u17ffa-zA-Z]{2,}", raw_txt))
                if not has_real_word or raw_txt.startswith("@") or raw_txt.startswith("#"):
                    to_delete.append(seg["id"])
                    continue

                # ៣. លុបអក្សរ Watermark ដដែលៗដែលលោតលើស 4 ដង (ឧ. ឈ្មោះ Channel ឬ ភាគទី...)
                if freq[norm_txt] >= 4 and len(norm_txt) <= 14:
                    to_delete.append(seg["id"])
                    continue

            if to_delete:
                with self.conn:
                    for sid in to_delete:
                        self.conn.execute("DELETE FROM segments WHERE id=?", (sid,))
            return len(to_delete)

    def split_segment_at_ms(self, seg_id: int, split_ms: int) -> bool:
        """កាត់បំបែក 1 ជួរវែងទៅជា 2 ជួរត្រង់ចំណុច Playhead (split_ms)"""
        with self._lock:
            seg = self.get_segment_by_id(seg_id)
            if not seg:
                return False

            start_ms = int(seg["start_ms"])
            end_ms = int(seg["end_ms"])
            if not (start_ms + 250 <= split_ms <= end_ms - 250):
                return False

            ratio = (split_ms - start_ms) / float(max(1, end_ms - start_ms))

            def split_text(txt: str):
                t = (txt or "").strip()
                if not t:
                    return "", ""
                if len(t) == 1:
                    return t, ""
                cut = max(1, min(len(t) - 1, int(len(t) * ratio)))
                space_idx = t.rfind(" ", 0, cut + 6)
                if space_idx > 1:
                    cut = space_idx
                return t[:cut].strip(), t[cut:].strip()

            zh1, zh2 = split_text(seg.get("zh_text", ""))
            kh1, kh2 = split_text(seg.get("kh_text", ""))
            voice_ov = seg.get("voice_override") or ""
            seq_idx = int(seg.get("seq_index") or 1)

            with self.conn:
                self.conn.execute(
                    "UPDATE segments SET end_ms=?, zh_text=?, kh_text=?, tts_audio_path='', status='Edited' WHERE id=?",
                    (split_ms - 15, zh1, kh1, seg_id),
                )
                self.conn.execute(
                    "INSERT INTO segments(project_id, seq_index, start_ms, end_ms, zh_text, kh_text, voice_override, tts_audio_path, status) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, '', 'Edited')",
                    (seg["project_id"], seq_idx, split_ms + 15, end_ms, zh2, kh2, voice_ov),
                )
            return True

    def fix_all_overlaps(self, project_id: int) -> int:
        """តម្រៀបម៉ោងគ្រប់ជួរកុំឲ្យជាន់គ្នា (end_ms <= next_start_ms - 25ms)"""
        with self._lock:
            segs = self.get_segments(int(project_id))
            if len(segs) < 2:
                return 0

            fixed_count = 0
            with self.conn:
                cur = self.conn.cursor()
                try:
                    for i in range(len(segs) - 1):
                        cur_s = int(segs[i]["start_ms"])
                        cur_e = max(cur_s + 150, int(segs[i]["end_ms"]))
                        next_s = int(segs[i + 1]["start_ms"])

                        if cur_e > next_s - 25:
                            if next_s - 25 >= cur_s + 150:
                                new_e = next_s - 25
                                cur.execute("UPDATE segments SET end_ms=? WHERE id=?", (int(new_e), int(segs[i]["id"])))
                                segs[i]["end_ms"] = new_e
                                fixed_count += 1
                            else:
                                new_e = max(cur_s + 150, cur_e)
                                new_next_s = new_e + 25
                                cur.execute("UPDATE segments SET end_ms=? WHERE id=?", (int(new_e), int(segs[i]["id"])))
                                cur.execute("UPDATE segments SET start_ms=? WHERE id=?", (int(new_next_s), int(segs[i + 1]["id"])))
                                segs[i]["end_ms"] = new_e
                                segs[i + 1]["start_ms"] = new_next_s
                                if int(segs[i + 1]["end_ms"]) <= new_next_s + 150:
                                    new_next_e = new_next_s + 350
                                    cur.execute("UPDATE segments SET end_ms=? WHERE id=?", (int(new_next_e), int(segs[i + 1]["id"])))
                                    segs[i + 1]["end_ms"] = new_next_e
                                fixed_count += 1
                finally:
                    cur.close()
            return fixed_count

    def auto_split_long_segments(self, project_id: int, max_chars: int = 12, max_duration_ms: int = 3800) -> int:
        """កាត់បំបែកគ្រប់ប្រយោគវែងៗទាំងអស់ក្នុង Project ឲ្យនៅខ្លីៗដោយស្វ័យប្រវត្តិ"""
        with self._lock:
            segs = self.get_segments(int(project_id))
            if not segs:
                return 0

            split_list = []
            has_split = False

            for seg in segs:
                zh = clean_chinese_text(seg.get("zh_text", ""))
                start_ms = int(seg.get("start_ms", 0))
                end_ms = int(seg.get("end_ms", start_ms + 1000))
                dur = end_ms - start_ms

                pieces = split_chinese_text(zh, max_chars=max_chars)
                if len(pieces) > 1 or dur > max_duration_ms:
                    has_split = True
                    total_chars = sum(max(1, len(p)) for p in pieces) if pieces else 1
                    cur_s = start_ms
                    kh = (seg.get("kh_text") or "").strip()

                    for idx, piece in enumerate(pieces if pieces else [zh]):
                        ratio = max(1, len(piece)) / float(total_chars)
                        piece_dur = max(450, int(round(dur * ratio)))
                        p_e = cur_s + piece_dur
                        if idx == len(pieces) - 1:
                            p_e = max(cur_s + 450, end_ms)

                        sub_kh = ""
                        if kh:
                            kh_len = max(1, int(len(kh) * ratio))
                            sub_kh = kh[:kh_len].strip()
                            kh = kh[kh_len:].strip()
                            if idx == len(pieces) - 1 and kh:
                                sub_kh = (sub_kh + " " + kh).strip()

                        split_list.append({
                            "start_ms": cur_s,
                            "end_ms": p_e,
                            "zh_text": piece,
                            "kh_text": sub_kh,
                            "voice_override": seg.get("voice_override", ""),
                            "status": "Edited" if sub_kh else "Pending",
                        })
                        cur_s = p_e + 25
                else:
                    split_list.append(seg)

            if not has_split:
                return 0

            with self.conn:
                self.conn.execute("DELETE FROM segments WHERE project_id=?", (project_id,))
                self.conn.executemany(
                    """INSERT INTO segments (
                           project_id, seq_index, start_ms, end_ms,
                           zh_text, kh_text, voice_override, tts_audio_path, status
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)""",
                    [
                        (
                            project_id,
                            idx,
                            item.get("start_ms", 0),
                            item.get("end_ms", 0),
                            item.get("zh_text", ""),
                            item.get("kh_text", ""),
                            item.get("voice_override", ""),
                            item.get("status", "Pending"),
                        )
                        for idx, item in enumerate(split_list, start=1)
                    ],
                )
            self.fix_all_overlaps(project_id)
            return len(split_list) - len(segs)

    def save_studio_preset(self, name: str, edits: dict):
        """រក្សាទុក Logo/Mask/Sub/Color settings ជាគំរូ Studio Preset"""
        clean_name = str(name).strip()
        if not clean_name:
            return
        cfg = json.dumps(edits or {}, ensure_ascii=False)
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute(
                        "INSERT INTO studio_presets(name, config_json) VALUES(?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET config_json=excluded.config_json",
                        (clean_name, cfg),
                    )
                finally:
                    cur.close()

    def get_studio_presets(self) -> list:
        """ទាញយកបញ្ជី Preset ទាំងអស់"""
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT id, name, config_json FROM studio_presets ORDER BY id DESC")
                rows = cur.fetchall()
                presets = []
                for r in rows:
                    try:
                        cfg = json.loads(r["config_json"])
                    except Exception:
                        cfg = {}
                    presets.append({"id": int(r["id"]), "name": str(r["name"]), "config": cfg})
                return presets
            finally:
                cur.close()

    def delete_studio_preset(self, preset_id: int):
        """លុប Preset"""
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute("DELETE FROM studio_presets WHERE id=?", (int(preset_id),))
                finally:
                    cur.close()

    # ==========================================
    # SERIES PROFILES & CHARACTER VOICE MEMORY
    # ==========================================

    @staticmethod
    def _decode_series_profile_row(row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["default_voice_map"] = json.loads(d.get("default_voice_map_json") or "{}")
        except Exception:
            d["default_voice_map"] = {}
        try:
            d["glossary"] = json.loads(d.get("glossary_json") or "[]")
        except Exception:
            d["glossary"] = []
        try:
            d["edits_preset"] = json.loads(d.get("edits_preset_json") or "{}")
        except Exception:
            d["edits_preset"] = {}
        return d

    def list_series_profiles(self) -> List[Dict[str, Any]]:
        """ទាញយកបញ្ជីសំណុំរឿងភាគទាំងអស់ (Series Profiles)"""
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT * FROM series_profiles ORDER BY series_name COLLATE NOCASE ASC, id DESC")
                return [self._decode_series_profile_row(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def get_series_profile(self, profile_id: int) -> Optional[Dict[str, Any]]:
        """ទាញយកព័ត៌មានលម្អិតនៃសំណុំរឿងភាគមួយតាម ID"""
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT * FROM series_profiles WHERE id=?", (int(profile_id),))
                row = cur.fetchone()
                return self._decode_series_profile_row(row) if row else None
            finally:
                cur.close()

    def save_series_profile(
        self,
        series_name: str,
        default_voice_map: Optional[Dict[str, Any]] = None,
        glossary: Optional[List[Dict[str, Any]]] = None,
        edits_preset: Optional[Dict[str, Any]] = None,
        intro_path: str = "",
        outro_path: str = "",
    ) -> int:
        """រក្សាទុក ឬអាប់ដេតសំណុំរឿងភាគ (Voice Memory + Glossary + Edits Preset + Intro/Outro)"""
        clean_name = str(series_name or "").strip()
        if not clean_name:
            raise ValueError("Series name cannot be empty.")
        voice_json = json.dumps(default_voice_map or {}, ensure_ascii=False)
        gloss_json = json.dumps(glossary or [], ensure_ascii=False)
        edits_json = json.dumps(edits_preset or {}, ensure_ascii=False)
        intro_s = str(intro_path or "").strip()
        outro_s = str(outro_path or "").strip()

        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute(
                        """
                        INSERT INTO series_profiles (
                            series_name, default_voice_map_json, glossary_json,
                            edits_preset_json, intro_path, outro_path
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(series_name) DO UPDATE SET
                            default_voice_map_json=excluded.default_voice_map_json,
                            glossary_json=excluded.glossary_json,
                            edits_preset_json=excluded.edits_preset_json,
                            intro_path=excluded.intro_path,
                            outro_path=excluded.outro_path
                        """,
                        (clean_name, voice_json, gloss_json, edits_json, intro_s, outro_s),
                    )
                    cur.execute("SELECT id FROM series_profiles WHERE series_name=?", (clean_name,))
                    row = cur.fetchone()
                    return int(row["id"]) if row else int(cur.lastrowid or 0)
                finally:
                    cur.close()

    def delete_series_profile(self, profile_id: int) -> bool:
        """លុបសំណុំរឿងភាគចេញពី Database"""
        with self._lock:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute("DELETE FROM series_profiles WHERE id=?", (int(profile_id),))
                    return cur.rowcount > 0
                finally:
                    cur.close()


    def replace_text_in_segments(
        self,
        project_id: int,
        find_text: str,
        replace_text: str,
        target: str = "kh",
        case_sensitive: bool = False,
        only_seg_id: int = None,
    ) -> int:
        """ស្វែងរក និងជំនួសពាក្យខុសក្នុងតារាង segments (អាចកែ 1 ជួរ ឬកែទាំងអស់)"""
        if not find_text:
            return 0
        segs = self.get_segments(project_id)
        if only_seg_id is not None:
            segs = [s for s in segs if int(s["id"]) == int(only_seg_id)]

        pattern = re.compile(re.escape(find_text), 0 if case_sensitive else re.IGNORECASE)
        updated_rows = 0

        with self.conn:
            for s in segs:
                new_kh = s.get("kh_text") or ""
                new_zh = s.get("zh_text") or ""
                changed = False

                if target in ("kh", "both") and new_kh:
                    replaced_kh, n_kh = pattern.subn(replace_text, new_kh)
                    if n_kh > 0:
                        new_kh = replaced_kh
                        changed = True

                if target in ("zh", "both") and new_zh:
                    replaced_zh, n_zh = pattern.subn(replace_text, new_zh)
                    if n_zh > 0:
                        new_zh = replaced_zh
                        changed = True

                if changed:
                    # សម្អាត tts_audio_path ចាស់ប្រសិនបើអត្ថបទខ្មែរត្រូវបានកែប្រែ ដើម្បីឲ្យបង្កើតសំឡេងថ្មីត្រឹមត្រូវ
                    if new_kh != (s.get("kh_text") or ""):
                        self.conn.execute(
                            "UPDATE segments SET zh_text=?, kh_text=?, tts_audio_path='' WHERE id=?",
                            (new_zh, new_kh, s["id"]),
                        )
                    else:
                        self.conn.execute(
                            "UPDATE segments SET zh_text=? WHERE id=?",
                            (new_zh, s["id"]),
                        )
                    updated_rows += 1
        return updated_rows

    # ==========================================
    # CLONED VOICES & HUMAN VOICE PRESETS
    # ==========================================

    def get_cloned_voices(self) -> List[Dict[str, Any]]:
        """ទាញយកបញ្ជីសំឡេងមនុស្សពិត និងសំឡេងដែលបានក្លូនទាំងអស់"""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM cloned_voices ORDER BY is_preset DESC, id ASC"
            )
            return [dict(r) for r in cur.fetchall()]

    def get_cloned_voice(self, voice_id: int) -> Optional[Dict[str, Any]]:
        """ទាញយកព័ត៌មានលម្អិតនៃសំឡេងក្លូនមួយ"""
        with self._lock:
            cur = self.conn.execute("SELECT * FROM cloned_voices WHERE id = ?", (voice_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def add_cloned_voice(
        self,
        name: str,
        sample_path: str = "",
        gender: str = "female",
        base_voice: str = "km-KH-SreymomNeural",
        pitch_shift: int = 0,
        formant_shift: float = 1.0,
        warmth: float = 1.2,
        brightness: float = 1.1,
        tempo_rate: float = 1.0,
        voice_color: str = "natural",
        fx: str = "",
        api_voice_id: str = "",
        is_preset: int = 0,
    ) -> int:
        """បន្ថែមសំឡេងមនុស្សពិត ឬសំឡេងក្លូនថ្មីចូលទៅក្នុង Database"""
        with self._lock:
            with self.conn:
                cur = self.conn.execute(
                    """
                    INSERT INTO cloned_voices
                    (name, sample_path, gender, base_voice, pitch_shift, formant_shift, warmth, brightness, tempo_rate, voice_color, fx, api_voice_id, is_preset)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name, sample_path, gender, base_voice, int(pitch_shift),
                        float(formant_shift), float(warmth), float(brightness),
                        float(tempo_rate), voice_color, fx, api_voice_id, int(is_preset),
                    ),
                )
                return cur.lastrowid

    def update_cloned_voice(self, voice_id: int, **kwargs) -> bool:
        """កែសម្រួលព័ត៌មានសំឡេងក្លូន"""
        if not kwargs:
            return False
        cols = []
        vals = []
        for k, v in kwargs.items():
            cols.append(f"{k} = ?")
            vals.append(v)
        vals.append(voice_id)
        with self._lock:
            with self.conn:
                cur = self.conn.execute(
                    f"UPDATE cloned_voices SET {', '.join(cols)} WHERE id = ?",
                    tuple(vals),
                )
                return cur.rowcount > 0

    def delete_cloned_voice(self, voice_id: int) -> bool:
        """លុបសំឡេងក្លូនចេញពី Database"""
        with self._lock:
            with self.conn:
                cur = self.conn.execute(
                    "DELETE FROM cloned_voices WHERE id = ? AND is_preset = 0",
                    (voice_id,),
                )
                return cur.rowcount > 0

