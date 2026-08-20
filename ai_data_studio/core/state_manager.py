"""Checkpoint motoru - SQLite tabanlı durum yönetimi ve veri kalıcılığı.

Mimari kuralı: Veritabanına doğrudan yalnızca bu modül erişir. Arayüz katmanı
hiçbir zaman doğrudan sqlite3.connect() çağırmaz; güncellemeleri kuyruk (queue)
olayları üzerinden alır. Böylece thread çakışmaları ve 'database is locked'
hataları engellenir.

Tek bağlantı ve threading.RLock ile güvenli, serileştirilmiş erişim sağlanır.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config

log = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_INTERRUPTED = "interrupted"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"
STATUS_DONE = "done"

# save_checkpoint ile guncellenebilecek kolonlar (SQL injection'a karsi beyaz liste)
_UPDATABLE = {
    "status", "current_step", "step_name", "generated_rows_count",
    "validated_rows_count", "schema_metadata", "random_seed", "raw_data_path",
    "output_path", "error", "progress", "domain", "seed_data_path",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    prompt               TEXT NOT NULL DEFAULT '',
    domain               TEXT NOT NULL DEFAULT '',
    provider             TEXT NOT NULL DEFAULT '',
    model                TEXT NOT NULL DEFAULT '',
    current_step         INTEGER NOT NULL DEFAULT 0,
    step_name            TEXT NOT NULL DEFAULT '',
    progress             REAL NOT NULL DEFAULT 0.0,
    generated_rows_count INTEGER NOT NULL DEFAULT 0,
    validated_rows_count INTEGER NOT NULL DEFAULT 0,
    schema_metadata      TEXT,
    random_seed          INTEGER NOT NULL DEFAULT 42,
    raw_data_path        TEXT,
    seed_data_path       TEXT,
    output_path          TEXT,
    error                TEXT
);

CREATE TABLE IF NOT EXISTS llm_calls (
    call_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER,
    created_at    TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    purpose       TEXT NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS validation_reports (
    report_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    report     TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_llm_calls_job ON llm_calls(job_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateManager:
    """Tek bağlantı, tek erisim noktasi. GUI asla dogrudan sqlite3.connect() çağırmaz."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or config.DB_PATH)
        self._lock = threading.RLock()
        # Bozuk veritabanindan kurtarildiysa tasinan yedegin yolu; GUI bunu okuyup
        # kullaniciya "gecmisiniz su dosyaya alindi" diyebilir. Saglamsa None.
        self.recovered_backup_path: Optional[str] = None
        self._conn = self._open_checked()
        log.debug("StateManager hazır: %s", self.db_path)

    # ------------------------------------------------------------------ #
    # Acilis ve bozulma kurtarmasi
    # ------------------------------------------------------------------ #
    def _connect(self) -> sqlite3.Connection:
        # sqlite3.connect() bozuk dosyada bile basarili olur; hata ilk gercek okumada
        # cikar. Yari acik baglantiyi kapatmadan birakirsak Windows dosyayi kilitli
        # tutar ve kurtarma adimi bozuk dosyayi yedege tasiyamaz.
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except BaseException:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            raise
        return conn

    def _open_checked(self) -> sqlite3.Connection:
        """Veritabanini acar; dosya bozuksa yedekleyip yenisini olusturur.

        Bozuk bir app_state.db onceden acilista istisna firlatiyordu - uygulama hic
        acilmiyordu. Is gecmisi degerli ama uygulamanin acilmasindan daha az kritik:
        bozuk dosya silinmez, yanina tasinir.
        """
        try:
            conn = self._connect()
        except sqlite3.DatabaseError as exc:
            log.warning("Veritabanı açılamadı (%s): %s", self.db_path, exc)
            return self._recover(str(exc))

        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            log.warning("Bütünlük denetimi çalıştırılamadı: %s", exc)
            try:
                conn.close()
            except sqlite3.Error:
                pass
            return self._recover(str(exc))

        result = (row[0] if row else "") or ""
        if result.lower() != "ok":
            log.warning("Bütünlük denetimi başarısız (%s): %s", self.db_path, result)
            try:
                conn.close()
            except sqlite3.Error:
                pass
            return self._recover(result)

        return conn

    def _recover(self, reason: str) -> sqlite3.Connection:
        """Bozuk dosyayi (ve WAL yan dosyalarini) yedege tasiyip temiz bir DB acar."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        main = Path(self.db_path)
        backup = main.with_name("%s.corrupt_%s" % (main.name, stamp))
        moved = False
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(main) + suffix)
            if not src.exists():
                continue
            try:
                src.replace(Path(str(backup) + suffix))
                moved = moved or suffix == ""
            except OSError as exc:  # pragma: no cover - dosya kilitliyse
                log.error("Bozuk veritabanı yedeklenemedi (%s): %s", src, exc)
                try:
                    src.unlink()
                except OSError:
                    pass

        self.recovered_backup_path = str(backup) if moved else None
        log.error(
            "Bozuk veritabanı yeniden oluşturuldu. Sebep: %s. Yedek: %s",
            reason, self.recovered_backup_path or "(alınamadı)",
        )
        return self._connect()

    # ------------------------------------------------------------------ #
    # Job yasam dongusu
    # ------------------------------------------------------------------ #
    def create_job(self, prompt: str, provider: str = "", model: str = "",
                   random_seed: int = config.DEFAULT_RANDOM_SEED,
                   domain: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO jobs (created_at, updated_at, status, prompt, domain, "
                "provider, model, random_seed) VALUES (?,?,?,?,?,?,?,?)",
                (_now(), _now(), STATUS_PENDING, prompt, domain, provider, model, random_seed),
            )
            self._conn.commit()
            job_id = int(cur.lastrowid)
        log.info("Job #%d oluşturuldu", job_id)
        return job_id

    def save_checkpoint(self, job_id: int, **fields: Any) -> None:
        """Job satirini günceller. Bilinmeyen alan verilirse ValueError."""
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError("Guncellenemeyen alan(lar): %s" % sorted(unknown))
        if not fields:
            return
        if "schema_metadata" in fields and not isinstance(fields["schema_metadata"], (str, type(None))):
            fields["schema_metadata"] = json.dumps(fields["schema_metadata"], ensure_ascii=False)

        assignments = ", ".join("%s = ?" % k for k in fields)
        values = list(fields.values()) + [_now(), job_id]
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET %s, updated_at = ? WHERE job_id = ?" % assignments, values
            )
            self._conn.commit()

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY job_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_job(self, job_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM validation_reports WHERE job_id = ?", (job_id,))
            self._conn.execute("DELETE FROM llm_calls WHERE job_id = ?", (job_id,))
            self._conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            self._conn.commit()

    def clear_history(self) -> None:
        """Tüm geçmiş işleri, raporları ve maliyet kayıtlarını siler."""
        with self._lock:
            self._conn.execute("DELETE FROM validation_reports")
            self._conn.execute("DELETE FROM llm_calls")
            self._conn.execute("DELETE FROM jobs")
            self._conn.commit()
        log.info("Tüm iş geçmişi temizlendi")

    # ------------------------------------------------------------------ #
    # Resume davranisi (Bolum 6.2)
    # ------------------------------------------------------------------ #
    def mark_stale_jobs_interrupted(self) -> int:
        """Acilista, önceki caliseden kalan 'running' job'lari 'interrupted' yapar."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE status = ?",
                (STATUS_INTERRUPTED, _now(), STATUS_RUNNING),
            )
            self._conn.commit()
            return cur.rowcount

    def get_resumable_job(self) -> Optional[Dict[str, Any]]:
        """Devam ettirilebilecek en son job. Yoksa None.

        GUI acilista bunu sorup kullanıcıya sorar:
        "Job #104, adım 45.000'den devam edilsin mi?"
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE status IN (?, ?) AND schema_metadata IS NOT NULL "
                "ORDER BY job_id DESC LIMIT 1",
                (STATUS_INTERRUPTED, STATUS_FAILED),
            ).fetchone()
        return dict(row) if row else None

    def get_schema(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Kayıtlı Schema Contract JSON'ini dict olarak dondurur."""
        job = self.get_job(job_id)
        if not job or not job.get("schema_metadata"):
            return None
        try:
            return json.loads(job["schema_metadata"])
        except json.JSONDecodeError:
            log.warning("Job #%s schema_metadata parse edilemedi", job_id)
            return None

    # ------------------------------------------------------------------ #
    # Maliyet takibi (Bolum 7)
    # ------------------------------------------------------------------ #
    def log_llm_call(self, job_id: Optional[int], provider: str, model: str,
                     input_tokens: int = 0, output_tokens: int = 0,
                     purpose: str = "") -> float:
        """LLM cagrisinin token kullanimini loglar, tahmini maliyeti dondurur."""
        cost = estimate_cost(model, input_tokens, output_tokens)
        with self._lock:
            self._conn.execute(
                "INSERT INTO llm_calls (job_id, created_at, provider, model, purpose, "
                "input_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?,?)",
                (job_id, _now(), provider, model, purpose,
                 int(input_tokens), int(output_tokens), cost),
            )
            self._conn.commit()
        return cost

    def get_cost_summary(self, job_id: Optional[int] = None) -> Dict[str, Any]:
        query = ("SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens),0) AS input_tokens, "
                 "COALESCE(SUM(output_tokens),0) AS output_tokens, "
                 "COALESCE(SUM(cost_usd),0.0) AS cost_usd FROM llm_calls")
        params: tuple = ()
        if job_id is not None:
            query += " WHERE job_id = ?"
            params = (job_id,)
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return dict(row)

    # ------------------------------------------------------------------ #
    # Validasyon raporlari
    # ------------------------------------------------------------------ #
    def save_report(self, job_id: int, report: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO validation_reports (job_id, created_at, report) VALUES (?,?,?)",
                (job_id, _now(), json.dumps(report, ensure_ascii=False, default=str)),
            )
            self._conn.commit()

    def get_report(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT report FROM validation_reports WHERE job_id = ? "
                "ORDER BY report_id DESC LIMIT 1", (job_id,)
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["report"])
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "StateManager":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Model fiyat tablosundan tahmini USD maliyeti. Bilinmeyen model -> 0.0."""
    pricing = config.MODEL_PRICING_USD_PER_MTOK.get(model)
    if not pricing:
        return 0.0
    in_rate, out_rate = pricing
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000, 6)


# --------------------------------------------------------------------------- #
# Surec genelinde tek bir StateManager ornegi
# --------------------------------------------------------------------------- #
_singleton: Optional[StateManager] = None
_singleton_lock = threading.Lock()


def get_state_manager() -> StateManager:
    """Uygulama genelinde paylasilan tek StateManager ornegini dondurur."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = StateManager()
        return _singleton
