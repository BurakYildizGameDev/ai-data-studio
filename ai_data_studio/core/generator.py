"""Generator - Kod üretimi, izole sandbox yürütme ve self-healing döngüsü.

Çekirdek felsefe: Ham veri satırları yerine veri üreten Python kodu üretilir.
Üretilen kod izole bir subprocess'te koşturulur (asla ana process'te exec() ile değil),
çıktının Schema Contract'a uyumu denetlenir; uymuyorsa hata geri beslenerek
MAX_CODEGEN_RETRIES denemede düzeltilir.

Sandbox güvenlik katmanları:
  1. AST tabanlı import allowlist ve tehlikeli çağrı filtreleme (static_import_check)
  2. İzole subprocess ve zaman aşımı denetimi (timeout)
  3. psutil tabanlı bellek watchdog thread'i
  4. Geçici, izole çalışma dizini
"""
from __future__ import annotations

import ast
import json
import logging
import re
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .. import config
from ..i18n import t
from .schema_contract import SchemaContract

log = logging.getLogger(__name__)

__all__ = [
    "SecurityError",
    "GenerationFailedError",
    "ExecutionResult",
    "static_import_check",
    "execute_in_sandbox",
    "sanity_check",
    "generate_and_execute",
    "diagnostic_hint",
]


class SecurityError(RuntimeError):
    """Üretilen kod sandbox politikasini ihlal ediyor."""


class GenerationFailedError(RuntimeError):
    """Self-healing dongusu MAX_RETRIES denemede başarılı olamadi."""


# Import disi yasakli isimler - dinamik kod calistirma / dosya-surec erisimi.
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "memoryview", "exit", "quit",
}
# Sandbox kacisina yol acan dunder attribute erisimleri.
FORBIDDEN_ATTRS = {
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__code__",
    "__builtins__", "__loader__", "__reduce__", "__reduce_ex__", "__class__",
    "__getattribute__", "__dict__",
}

# Kodun tanimlamasi gereken fonksiyon adlari (ilk bulunan kullanilir).
# Sira onemli: harness ilk bulunan callable'i kullanir. generate_dataset once
# gelir, boylece iliskisel kod yazan bir model tek tablolu fallback'e dusmez.
ENTRYPOINT_NAMES = ("generate_dataset", "generate_data", "generate",
                    "build_dataframe", "main")

# İzole sandbox harness'i - kullanıcı kodunu import eder, RNG'leri seed'ler, çıktıyı parquet yazar.
_RUNNER_TEMPLATE = '''# -*- coding: utf-8 -*-
"""Isolated sandbox execution harness."""
import json
import os
import random
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

N_ROWS = int(sys.argv[1])
SEED = int(sys.argv[2])
OUT_PATH = sys.argv[3]

# --- Reproducibility: üretilen kod import EDILMEDEN önce tüm RNG'ler seed'lenir ---
random.seed(SEED)
try:
    import numpy as np
    np.random.seed(SEED)
except Exception:
    np = None
try:
    from faker import Faker
    Faker.seed(SEED)
except Exception:
    pass

try:
    import user_code
except Exception:
    traceback.print_exc()
    sys.exit(3)

ENTRYPOINTS = {entrypoints!r}
fn = None
for name in ENTRYPOINTS:
    candidate = getattr(user_code, name, None)
    if callable(candidate):
        fn = candidate
        break

if fn is None:
    sys.stderr.write(
        "Üretilen kodda beklenen fonksiyon bulunamadı. Su adlardan biri tanimlanmali: "
        + ", ".join(ENTRYPOINTS)
        + "\\nBulunan üst duzey adlar: "
        + ", ".join(sorted(n for n in dir(user_code) if not n.startswith("_")))
        + "\\n"
    )
    sys.exit(4)

try:
    import inspect
    n_params = len([
        p for p in inspect.signature(fn).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ])
    if n_params >= 2:
        df = fn(N_ROWS, SEED)
    elif n_params == 1:
        df = fn(N_ROWS)
    else:
        df = fn()
except Exception:
    traceback.print_exc()
    sys.exit(5)

try:
    import pandas as pd
except Exception:
    traceback.print_exc()
    sys.exit(6)

# Donus ya tek bir DataFrame (tek tablolu) ya da {{tablo_adi: DataFrame}}
# sozlugu (iliskisel) olabilir. Tek tablo, sozlugun N=1 ozel durumudur.
IDENT_OK = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").fullmatch

if isinstance(df, pd.DataFrame):
    tables = {{"": df}}
elif isinstance(df, dict) and df:
    bad_type = sorted(str(k) for k, v in df.items() if not isinstance(v, pd.DataFrame))
    if bad_type:
        sys.stderr.write(
            "Tablo sozlugundeki su anahtarlar pandas.DataFrame degil: %s\\n"
            % ", ".join(bad_type)
        )
        sys.exit(7)
    bad_name = sorted(str(k) for k in df if not IDENT_OK(str(k)))
    if bad_name:
        sys.stderr.write(
            "Gecersiz tablo adlari: %s. Tablo adlari harf/rakam/alt cizgi "
            "icermeli ve rakamla baslamamali.\\n" % ", ".join(bad_name)
        )
        sys.exit(7)
    tables = {{str(k): v for k, v in df.items()}}
else:
    sys.stderr.write(
        "Fonksiyon pandas.DataFrame ya da {{tablo_adi: DataFrame}} sozlugu "
        "dondurmeli, %s dondu.\\n" % type(df).__name__
    )
    sys.exit(7)

empty = sorted(name or "<tek tablo>" for name, frame in tables.items() if len(frame) == 0)
if empty:
    sys.stderr.write("Su tablolar bos (0 satir): %s\\n" % ", ".join(empty))
    sys.exit(8)

out_dir = os.path.dirname(os.path.abspath(OUT_PATH))
manifest = {{}}
for name, frame in tables.items():
    # Tek tablolu cikti bugunku yolu korur; iliskisel cikti kardes dosyalara yazilir.
    path = OUT_PATH if name == "" else os.path.join(out_dir, "table_%s.parquet" % name)
    written = path
    try:
        frame.to_parquet(path, index=False)
    except Exception:
        # Parquet motoru yoksa CSV'ye geri düş (UTF-8).
        try:
            written = path + ".csv"
            frame.to_csv(written, index=False, encoding="utf-8")
        except Exception:
            traceback.print_exc()
            sys.exit(9)
    manifest[name] = {{
        "rows": int(len(frame)),
        "columns": [str(c) for c in frame.columns],
        "path": os.path.basename(written),
    }}

# Geriye uyum: rows/columns her zaman birincil tabloyu anlatir.
primary = manifest.get("") or manifest[sorted(manifest)[0]]
sys.stdout.write(json.dumps({{
    "rows": primary["rows"],
    "columns": primary["columns"],
    "tables": {{k: v for k, v in manifest.items() if k != ""}},
}}))
'''


@dataclass
class ExecutionResult:
    """execute_in_sandbox çıktısı."""

    success: bool
    dataframe: Optional[pd.DataFrame] = None
    traceback: str = ""
    stdout: str = ""
    duration_s: float = 0.0
    row_count: int = 0
    output_path: Optional[Path] = None
    killed_reason: str = ""
    # Iliskisel uretimde tablo adi -> DataFrame. Tek tablolu kodda tek girdi
    # icerir ve degeri `dataframe` ile aynidir; boylece tuketiciler her iki
    # durumda da `tables` uzerinden gezebilir.
    tables: Dict[str, pd.DataFrame] = field(default_factory=dict)

    @property
    def is_relational(self) -> bool:
        return len(self.tables) > 1

    @property
    def row_counts(self) -> Dict[str, int]:
        """Tablo adi -> satir sayisi."""
        return {name: len(frame) for name, frame in self.tables.items()}


# --------------------------------------------------------------------------- #
# 1. Statik guvenlik denetimi
# --------------------------------------------------------------------------- #
def static_import_check(code: str, allowed: Optional[set] = None) -> None:
    """Kodu calistirmadan AST üzerinde denetler. İhlalde SecurityError.



    Denetimler:

      * import / from-import koklerinin allowlist'te olmasi

      * eval/exec/compile/__import__/open gibi isimlerin kullanilmamasi

      * __subclasses__ / __globals__ gibi kacis attribute'larina erisilmemesi

    """
    allowed = allowed if allowed is not None else config.ALLOWED_IMPORTS
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SecurityError(
            "Üretilen kod parse edilemedi (satır %s): %s" % (exc.lineno, exc.msg)
        ) from exc

    violations: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in allowed:
                    violations.append("izin verilmeyen import: %s (satır %s)" % (root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level and not root:
                violations.append("goreli import yasak (satır %s)" % node.lineno)
            elif root not in allowed:
                violations.append("izin verilmeyen import: %s (satır %s)" % (root, node.lineno))
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            violations.append("yasakli isim kullanimi: %s (satır %s)" % (node.id, node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            violations.append("yasakli attribute erisimi: %s (satır %s)" % (node.attr, node.lineno))

    if violations:
        raise SecurityError("Sandbox politikasi ihlali -> " + "; ".join(violations))


# --------------------------------------------------------------------------- #
# 2. Bellek watchdog (psutil - Windows uyumlu)
# --------------------------------------------------------------------------- #
class _MemoryWatchdog(threading.Thread):
    """Process agacinin RSS kullanimini izler, esik asilirsa oldurur."""

    # Ornekleme araligi. Watchdog bir ust sinir DEGIL, bir orneklemedir: iki ornek
    # arasinda ayrilan bellek gorulmez. 0.4 sn'de bir yoklarken 256 MB limitli bir
    # kosu 2451 MB'a cikmisti. 0.1 sn kademeli ayiran kodu erken yakalar; tek
    # seferde dev bir dizi ayiran kodu hicbir ornekleme araligi yakalayamaz -
    # bunun icin isletim sistemi seviyesinde sert sinir gerekir (README'de yazili).
    def __init__(self, proc: subprocess.Popen, limit_mb: int,
                 cancel_event: Optional[threading.Event] = None, interval: float = 0.1):
        super().__init__(daemon=True, name="sandbox-memory-watchdog")
        self.proc = proc
        self.limit_bytes = limit_mb * 1024 * 1024
        self.cancel_event = cancel_event
        self.interval = interval
        self.peak_mb = 0.0
        self.killed_reason = ""
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            import psutil
        except Exception:  # pragma: no cover - psutil yoksa watchdog devre disi
            log.warning("psutil yok - bellek watchdog devre disi")
            return
        try:
            ps_proc = psutil.Process(self.proc.pid)
        except Exception:
            return

        child_sweep_every = max(1, int(round(1.0 / max(self.interval, 0.01))))
        sweeps = child_sweep_every            # ilk turda cocuklar da taransin
        last_child_rss = 0

        while not self._stop.is_set() and self.proc.poll() is None:
            if self.cancel_event is not None and self.cancel_event.is_set():
                self.killed_reason = "Kullanıcı tarafından iptal edildi"
                kill_process_tree(self.proc)
                return
            try:
                rss = ps_proc.memory_info().rss
                # Cocuk sureclerin taranmasi Windows'ta tum surec listesini gezer -
                # 10 Hz'de pahali. Sandbox kodu normalde surec baslatamaz (allowlist),
                # bu yuzden cocuklar saniyede bir taranir, ebeveyn her ornekte.
                sweeps += 1
                if sweeps >= child_sweep_every:
                    sweeps = 0
                    child_rss = 0
                    for child in ps_proc.children(recursive=True):
                        try:
                            child_rss += child.memory_info().rss
                        except Exception:
                            pass
                    last_child_rss = child_rss
                rss += last_child_rss
            except Exception:
                return
            self.peak_mb = max(self.peak_mb, rss / 1024 / 1024)
            if rss > self.limit_bytes:
                self.killed_reason = (
                    "Bellek limiti asildi: %.0f MB > %d MB (tepe %.0f MB)"
                    % (rss / 1024 / 1024, self.limit_bytes // 1024 // 1024, self.peak_mb)
                )
                log.warning("Sandbox %s - process oldurunuyor", self.killed_reason)
                kill_process_tree(self.proc)
                return
            self._stop.wait(self.interval)


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Process'i ve tüm cocuklarini oldurur (Windows/POSIX)."""
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 3. Sandbox calistirma
# --------------------------------------------------------------------------- #
def execute_in_sandbox(
    code: str,
    n_rows: int = config.DEFAULT_ROW_TARGET,
    seed: int = config.DEFAULT_RANDOM_SEED,
    timeout: int = config.SANDBOX_TIMEOUT_S,
    memory_limit_mb: int = config.SANDBOX_MEMORY_LIMIT_MB,
    cancel_event: Optional[threading.Event] = None,
    keep_workdir: bool = False,
) -> ExecutionResult:
    """LLM'in urettigi kodu izole bir subprocess'te çalıştırır.

    Kod, ``generate_data(n_rows, seed) -> pd.DataFrame`` imzali bir fonksiyon
    tanimlamalidir; harness bu fonksiyonu cagirip ciktiyi parquet olarak yazar.
    """
    static_import_check(code)

    workdir = Path(tempfile.mkdtemp(prefix="aids_sbx_", dir=str(config.WORK_DIR)))
    user_path = workdir / "user_code.py"
    runner_path = workdir / "_runner.py"
    out_path = workdir / "output.parquet"

    user_path.write_text(code, encoding="utf-8")
    runner_path.write_text(
        _RUNNER_TEMPLATE.format(entrypoints=ENTRYPOINT_NAMES), encoding="utf-8"
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MPLBACKEND"] = "Agg"

    started = time.perf_counter()
    watchdog: Optional[_MemoryWatchdog] = None
    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            [sys.executable, str(runner_path), str(n_rows), str(seed), str(out_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workdir),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        watchdog = _MemoryWatchdog(proc, memory_limit_mb, cancel_event)
        watchdog.start()

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except Exception:
                stdout, stderr = "", ""
            return ExecutionResult(
                success=False,
                traceback="Zaman aşımı: kod %d saniyede bitmedi. Daha verimli, "
                          "vektorlestirilmis (numpy/pandas) üretim yaz; satır bazli "
                          "Python dongusu kullanma." % timeout,
                stdout=stdout or "",
                duration_s=time.perf_counter() - started,
                killed_reason="timeout",
            )
        finally:
            if watchdog is not None:
                watchdog.stop()

        duration = time.perf_counter() - started

        if watchdog is not None and watchdog.killed_reason:
            return ExecutionResult(
                success=False,
                traceback=watchdog.killed_reason
                + ". Bellegi daha verimli kullan: veriyi parca parca uret veya "
                  "daha dar dtype (int32/float32) seç.",
                stdout=stdout or "",
                duration_s=duration,
                killed_reason=watchdog.killed_reason,
            )

        if proc.returncode != 0:
            return ExecutionResult(
                success=False,
                traceback=(stderr or "").strip() or "Bilinmeyen hata (exit %s)" % proc.returncode,
                stdout=stdout or "",
                duration_s=duration,
            )

        tables, primary_name = _load_tables(out_path, stdout or "")
        if not tables:
            return ExecutionResult(
                success=False,
                traceback="Kod hatasiz bitti ama çıktı dosyasi olusmadi.",
                stdout=stdout or "",
                duration_s=duration,
            )

        df = tables[primary_name]
        if len(tables) > 1:
            log.info("Sandbox OK: %d tablo (%s), %.1f sn, tepe bellek %.0f MB",
                     len(tables),
                     ", ".join("%s=%s" % (n, format(len(f), ","))
                               for n, f in sorted(tables.items())),
                     duration, watchdog.peak_mb if watchdog else 0)
        else:
            log.info("Sandbox OK: %s satır, %.1f sn, tepe bellek %.0f MB",
                     format(len(df), ","), duration, watchdog.peak_mb if watchdog else 0)
        return ExecutionResult(
            success=True,
            dataframe=df,
            tables=tables,
            stdout=stdout or "",
            duration_s=duration,
            row_count=len(df),
            output_path=out_path,
        )
    finally:
        if proc is not None and proc.poll() is None:
            kill_process_tree(proc)
        if not keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def _load_tables(out_path: Path, stdout: str) -> Tuple[Dict[str, pd.DataFrame], str]:
    """Harness ciktisini okur.

    Harness stdout'a bir manifest yazar; iliskisel uretimde ``tables`` anahtari
    tablo adi -> {rows, columns, path} esler. Tek tablolu uretimde manifest bos
    kalir ve tek parquet ``out_path``ten okunur.

    Returns:
        ({tablo_adi: DataFrame}, birincil_tablo_adi). Hicbir sey okunamazsa
        ({}, "") doner.
    """
    manifest: Dict[str, Any] = {}
    try:
        payload = json.loads(stdout.strip() or "{}")
        if isinstance(payload, dict):
            raw = payload.get("tables")
            if isinstance(raw, dict):
                manifest = raw
    except (ValueError, TypeError):
        manifest = {}

    if not manifest:
        df = _load_output(out_path)
        if df is None:
            return {}, ""
        return {"": df}, ""

    tables: Dict[str, pd.DataFrame] = {}
    work_dir = out_path.parent
    for name, info in manifest.items():
        rel = (info or {}).get("path") if isinstance(info, dict) else None
        if not rel:
            continue
        frame = _load_output(work_dir / str(rel))
        if frame is not None:
            tables[str(name)] = frame

    if not tables:
        return {}, ""
    # Birincil tablo: manifestteki ilk (uretim sirasindaki ilk) tablo.
    primary = next((n for n in manifest if n in tables), sorted(tables)[0])
    return tables, primary


def _load_output(out_path: Path) -> Optional[pd.DataFrame]:
    """Harness'in yazdigi parquet (veya CSV fallback) dosyasini okur."""
    if out_path.exists():
        try:
            return pd.read_parquet(out_path)
        except Exception as exc:
            log.error("Parquet okunamadı: %s", exc)
    csv_path = Path(str(out_path) + ".csv")
    if csv_path.exists():
        try:
            return pd.read_csv(csv_path, encoding="utf-8")
        except Exception as exc:
            log.error("CSV okunamadı: %s", exc)
    return None


# --------------------------------------------------------------------------- #
# 4. Sema uyumu kontrolu (self-healing feedback kaynagi)
# --------------------------------------------------------------------------- #
# sanity_check toleranslari.
#
# ONEMLI: Bu kontrol "veri TEMIZ mi?" diye sormaz - "veri YAPISAL olarak kullanilabilir mi?"
# diye sorar. Mimari geregi uretilen kod bilerek %10-20 gurultu (aykiri deger, kural
# ihlali, birkac null) icerir; onlari ayiklamak Discriminator'in (validator.py) isidir.
# Bu yuzden sinir ihlali toleranslari genis: amac kasitli gurultuyu degil, SISTEMATIK
# hatayi yakalamak (ornegin modelin yasi 0-1 arasina normalize etmesi).
BOUNDS_VIOLATION_TOLERANCE = 0.25   # sinir disi deger orani bu esigi asarsa sistematik hata
NULL_TOLERANCE = 0.15               # nullable olmayan kolonda kabul edilen bos deger orani
CATEGORY_VIOLATION_TOLERANCE = 0.10


def sanity_check(df: pd.DataFrame, schema: SchemaContract,
                 min_ratio: float = 0.5) -> List[str]:
    """Üretilen veriyi Schema Contract'a karsi YAPISAL olarak denetler.

    Donen liste boş degilse self-healing dongusu bunu LLM'e geri besler.
    Kasitli gurultu sorun sayilmaz - bkz. yukarıdaki tolerans notu.
    """
    issues: List[str] = []

    expected = schema.column_names
    missing = expected - set(df.columns)
    if missing:
        issues.append("Eksik kolonlar: %s" % sorted(missing))

    extra = set(df.columns) - expected
    if extra:
        issues.append("Semada olmayan fazladan kolonlar: %s" % sorted(extra))

    if len(df) < schema.row_count_target * min_ratio:
        issues.append(
            "Satır sayısı çok düşük: %s üretildi, hedef %s (en az %%%d bekleniyor)"
            % (format(len(df), ","), format(schema.row_count_target, ","), int(min_ratio * 100))
        )

    for col in schema.columns:
        if col.name not in df.columns:
            continue
        series = df[col.name]

        if not col.nullable:
            null_ratio = float(series.isna().mean())
            if null_ratio > NULL_TOLERANCE:
                issues.append(
                    "'%s' kolonunun %%%.1f'i boş - nullable değil, bu kadar çok boş değer "
                    "üretim mantiginda hata olduğunu gösterir"
                    % (col.name, null_ratio * 100)
                )

        if col.is_numeric:
            if not pd.api.types.is_numeric_dtype(series):
                issues.append("'%s' sayısal olmalı ama dtype '%s'" % (col.name, series.dtype))
                continue
            clean = series.dropna()
            if clean.empty:
                issues.append("'%s' kolonunda hiç geçerli sayısal değer yok" % col.name)
                continue
            if col.min is not None:
                below = float((clean < col.min).mean())
                if below > BOUNDS_VIOLATION_TOLERANCE:
                    issues.append(
                        "'%s' degerlerinin %%%.0f'i min sinirinin (%s) altında - kasitli "
                        "gurultu için çok yüksek, olceklendirme hatası olabilir"
                        % (col.name, below * 100, col.min)
                    )
            if col.max is not None:
                above = float((clean > col.max).mean())
                if above > BOUNDS_VIOLATION_TOLERANCE:
                    issues.append(
                        "'%s' degerlerinin %%%.0f'i max sinirinin (%s) üzerinde - kasitli "
                        "gurultu için çok yüksek, olceklendirme hatası olabilir"
                        % (col.name, above * 100, col.max)
                    )
            if col.type == "int" and not pd.api.types.is_integer_dtype(series):
                if not (clean % 1 == 0).all():
                    issues.append("'%s' tam sayı olmalı ama ondalikli degerler iceriyor" % col.name)

        elif col.type == "bool":
            if col.target_ratio is not None:
                try:
                    actual = float(series.astype(bool).mean())
                except Exception:
                    issues.append("'%s' boolean'a cevrilemiyor (dtype %s)" % (col.name, series.dtype))
                    continue
                if abs(actual - col.target_ratio) > max(0.05, col.target_ratio * 0.5):
                    issues.append(
                        "'%s' True orani %.3f, hedef %.3f - hedefe çok uzak"
                        % (col.name, actual, col.target_ratio)
                    )

        elif col.type == "category" and col.categories:
            allowed = set(col.categories)
            unexpected_ratio = float((~series.dropna().isin(allowed)).mean()) if len(series.dropna()) else 0.0
            if unexpected_ratio > CATEGORY_VIOLATION_TOLERANCE:
                unexpected = sorted(map(str, set(series.dropna().unique()) - allowed))[:10]
                issues.append("'%s' satirlarinin %%%.0f'i semada olmayan kategoriler iceriyor: %s"
                              % (col.name, unexpected_ratio * 100, unexpected))

    return issues


# --------------------------------------------------------------------------- #
# 5. Self-healing döngüsü
# --------------------------------------------------------------------------- #
def _sanity_check_tables(tables, contract) -> List[str]:
    """Her tabloyu kendi semasina karsi denetler, sorunlari tablo adiyla etiketler.

    Satir sayisi kontrolu YALNIZCA kok tabloda uygulanir: cocuk tablolarin
    buyuklugu kardinaliteden turer, semadaki row_count_target onlar icin sadece
    bir ipucudur.
    """
    issues: List[str] = []
    for schema in contract.tables:
        name = schema.table_name
        df = tables.get(name)
        if df is None:
            issues.append("'%s' tablosu uretilmedi" % name)
            continue
        is_root = name == contract.root_table
        for issue in sanity_check(df, schema, min_ratio=0.5 if is_root else 0.0):
            issues.append("[%s] %s" % (name, issue))

    unexpected = sorted(set(tables) - {t.table_name for t in contract.tables})
    if unexpected:
        issues.append("Sozlesmede olmayan fazladan tablolar: %s" % unexpected)
    return issues


def _generation_loop(
    contract,
    llm_client,
    relational: bool,
    max_retries: int = config.MAX_CODEGEN_RETRIES,
    timeout: int = config.SANDBOX_TIMEOUT_S,
    cancel_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[Dict[str, pd.DataFrame], str, Dict[str, Any]]:
    """Kod uret -> calistir -> denetle -> hatada LLM'e geri besle.

    Tek tablolu ve iliskisel uretim ayni dongudur; fark yalnizca hangi LLM
    metodunun cagrildigi ve denetimin tek tabloya mi tum tablolara mi
    uygulandigidir.

    Returns:
        ({tablo_adi: DataFrame}, çalışan_kod, meta)
    """
    def emit(message: str, level: str = config.PROGRESS_INFO,
             sandbox: bool = False) -> None:
        """Alt adım mesajı.

        ``sandbox`` bu satırın sandbox aşamasına ait olduğunu söyler; orchestrator
        adım numarasını buradan seçer. Önceden mesajın içinde "sandbox" kelimesi
        aranıyordu - çeviriyle bozulacak bir bağ.
        """
        log.info(message)
        if on_progress is not None:
            on_progress(message, level, sandbox)

    def check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationFailedError(t("codegen.cancelled"))

    root_schema = contract.table(contract.root_table)
    fix_context = contract if relational else root_schema

    check_cancel()
    emit(t("codegen.starting"))
    if relational:
        code = llm_client.generate_dataset_code(contract)
        emit(sandbox=True,
             message=t("codegen.written_relational", tables=len(contract.tables),
                       lines=len(code.splitlines())))
    else:
        code = llm_client.generate_code(root_schema)
        emit(sandbox=True,
             message=t("codegen.written", lines=len(code.splitlines())))

    history: List[str] = []
    signatures: set = set()
    feedback = ""

    for attempt in range(1, max_retries + 1):
        check_cancel()
        emit(t("codegen.attempt", attempt=attempt, total=max_retries),
             sandbox=True)

        result = execute_in_sandbox(
            code,
            n_rows=root_schema.row_count_target,
            seed=contract.random_seed,
            timeout=timeout,
            cancel_event=cancel_event,
        )
        check_cancel()

        if not result.success:
            feedback = "Kod calistirilirken hata olustu:\n%s" % result.traceback
            hint = diagnostic_hint(result.traceback)
            if hint:
                feedback += "\n\nNASIL DUZELTILIR:\n%s" % hint
            emit(t("codegen.attempt_failed", attempt=attempt,
                   error=_first_line(result.traceback)),
                 level=config.PROGRESS_WARNING)
            if hint:
                emit("  -> " + t("codegen.hint", hint=_first_line(hint, 120)))
        else:
            tables = dict(result.tables)
            if not relational:
                # Tek tablolu kod isimsiz doner; sozlesmedeki adla eslestir.
                tables = {contract.root_table: result.dataframe}
            issues = _sanity_check_tables(tables, contract)
            if not issues:
                if relational:
                    emit(t("codegen.attempt_ok_relational", attempt=attempt,
                           tables=len(tables),
                           seconds="%.1f" % result.duration_s,
                           counts=", ".join("%s=%s" % (n, format(len(f), ","))
                                            for n, f in sorted(tables.items()))))
                else:
                    primary = tables[contract.root_table]
                    emit(t("codegen.attempt_ok", attempt=attempt,
                           rows=format(len(primary), ","),
                           seconds="%.1f" % result.duration_s,
                           columns=len(primary.columns)))
                meta = {
                    "attempts": attempt,
                    "duration_s": round(result.duration_s, 2),
                    "issues_history": history,
                    "row_count": len(tables[contract.root_table]),
                    "row_counts": {n: int(len(f)) for n, f in tables.items()},
                    "relational": relational,
                }
                return tables, code, meta
            feedback = "Üretilen veri şema ile uyusmuyor:\n- " + "\n- ".join(issues)
            emit(t("codegen.schema_mismatch", attempt=attempt, count=len(issues)))
            for issue in issues[:3]:
                emit("  -> " + t("codegen.mismatch_item",
                                  issue=_first_line(issue, 110)))
            if len(issues) > 3:
                emit("  -> " + t("codegen.mismatch_more", count=len(issues) - 3))

        if not result.success:
            history_entry = _first_line(result.traceback, 200)
            signature = _error_signature(result.traceback)
        else:
            history_entry = _first_line(feedback, 200)
            signature = _error_signature(feedback)

        repeated = signature in signatures
        signatures.add(signature)
        history.append(history_entry)

        if attempt == max_retries:
            raise GenerationFailedError(
                t("codegen.gave_up", attempts=max_retries, error=feedback))

        check_cancel()
        if repeated:
            # Kucuk yerel modeller ayni tuzaga defalarca dusebiliyor; ayni hatayi
            # tekrar gorursek "yamala" demek yerine yaklasimi degistirmesini isteriz.
            emit(t("codegen.repeated_error"), level=config.PROGRESS_WARNING)
        else:
            emit(t("codegen.feeding_back"))
        try:
            code = llm_client.fix_code(previous_code=code, error_feedback=feedback,
                                       schema=fix_context, history=history, escalate=repeated)
        except SecurityError:
            raise
        except TypeError:
            # Eski imzali istemciler (history/escalate bilmeyen) icin geriye uyumluluk
            code = llm_client.fix_code(previous_code=code, error_feedback=feedback,
                                       schema=fix_context)
        except Exception as exc:
            raise GenerationFailedError(
                t("codegen.fix_call_failed", error=exc)) from exc

    raise GenerationFailedError(t("codegen.unexpected_state"))


def generate_and_execute(
    schema: SchemaContract,
    llm_client,
    max_retries: int = config.MAX_CODEGEN_RETRIES,
    timeout: int = config.SANDBOX_TIMEOUT_S,
    cancel_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[pd.DataFrame, str, Dict[str, Any]]:
    """Tek tablolu uretim: kod uret -> calistir -> denetle -> duzelt.

    Returns:
        (dataframe, çalışan_kod, meta) - meta: attempts, duration_s, issues_history
    """
    from .dataset_contract import DatasetContract

    contract = DatasetContract.from_schema(schema)
    tables, code, meta = _generation_loop(
        contract, llm_client, relational=False, max_retries=max_retries,
        timeout=timeout, cancel_event=cancel_event, on_progress=on_progress,
    )
    return tables[contract.root_table], code, meta


def generate_dataset_and_execute(
    contract,
    llm_client,
    max_retries: int = config.MAX_CODEGEN_RETRIES,
    timeout: int = config.SANDBOX_TIMEOUT_S,
    cancel_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[Dict[str, pd.DataFrame], str, Dict[str, Any]]:
    """Iliskisel uretim: tum tablolari tek seferde uretir ve denetler.

    Tek tablolu bir sozlesme verilirse (``is_relational`` False) otomatik olarak
    tek tablolu yola duser - N=1 ozel durumu.

    Returns:
        ({tablo_adi: DataFrame}, çalışan_kod, meta)
    """
    return _generation_loop(
        contract, llm_client, relational=contract.is_relational,
        max_retries=max_retries, timeout=timeout,
        cancel_event=cancel_event, on_progress=on_progress,
    )


# Sik gorulen hata siniflari -> modele verilecek SOMUT duzeltme talimati.
#
# Yerel/kucuk modeller ham traceback'ten dogru cikarimi cogu zaman yapamaz ve ayni
# hataya tekrar duser. Hatanin kokunu taniyip "ne yapmasi gerektigini" acikca
# soylemek, self-healing dongusunun basari oranini belirgin sekilde artirir.
_ERROR_HINTS: List[Tuple[str, str]] = [
    (
        "cannot cast ufunc",
        "DTYPE HATASI: Bir tam sayı (int) dizisine yerinde (+=, -=, *=) ondalikli değer "
        "ekliyorsun. Tüm ara hesaplari float64 olarak yap, tam sayiya cevirmeyi EN SONDA "
        "tek seferde yap. Ornek: `x = x.astype(float); x += 0.5 * y; x = x.round().astype(int)` "
        "veya yerinde islem yerine `x = x + 0.5 * y` yaz.",
    ),
    (
        "unknown formatter",
        "FAKER HATASI: Faker'in sablon API'lerini (pystr_format, bothify, lexify, numerify) "
        "kullaniyorsun; bunlar str.format() gibi calismaz. Bu cagrilari tamamen kaldir. "
        "Kalipli string uretmen gerekiyorsa numpy kullan: "
        "`np.char.add('v1.', rng.integers(0, 20, n_rows).astype(str))`.",
    ),
    (
        "could not broadcast",
        "SEKIL (SHAPE) HATASI: Farkli uzunlukta dizileri birlestiriyorsun. Her kolonun "
        "tam olarak n_rows uzunlugunda oldugundan emin ol; maskelenmis atamalarda "
        "`arr[mask] = değer` kullan ve sag tarafin uzunlugunun `mask.sum()` olduğunu dogrula.",
    ),
    (
        "shape mismatch",
        "SEKIL (SHAPE) HATASI: Maskeli atamada sag tarafin uzunlugu maskeyle uyusmuyor. "
        "`arr[mask] = rng.uniform(a, b, mask.sum())` bicimini kullan.",
    ),
    (
        "zaman aşımı",
        "PERFORMANS: Kod çok yavas. Python dongusu (for/while/list comprehension) ile satır "
        "uretmeyi tamamen birak; her kolonu tek bir vektorlestirilmis numpy çağrısıyla uret. "
        "Faker kullaniyorsan en fazla 500 degerlik bir havuz üretip numpy ile ornekle.",
    ),
    (
        "bellek limiti",
        "BELLEK: Çok fazla ara dizi tutuyorsun. Daha dar dtype seç (int32/float32), "
        "gereksiz kopyalardan kacin ve ara değişkenleri yeniden kullan.",
    ),
    (
        "truth value of an array",
        "MANTIK HATASI: Bir numpy dizisini `if` icinde kullaniyorsun. Eleman bazli kosullar "
        "için `np.where(kosul, a, b)` veya boolean maske kullan.",
    ),
    (
        "not defined",
        "TANIMSIZ AD: Tanimlamadigin bir değişkeni/fonksiyonu kullaniyorsun. Dosyayi bastan "
        "sona gozden gecir ve her adin kullanilmadan önce tanimlandigindan emin ol.",
    ),
    (
        "unhashable",
        "TIP HATASI: Liste/dizi gibi bir nesneyi sözlük anahtarı veya kume elemani yapiyorsun. "
        "Bunun yerine numpy dizisi üzerinde dogrudan islem yap.",
    ),
]


def diagnostic_hint(traceback_text: str) -> str:
    """Hatanin kokunu taniyip modele somut bir duzeltme talimati dondurur.

    Taninmayan hata için boş string döner (ham traceback zaten iletiliyor).
    """
    lowered = (traceback_text or "").lower()
    for needle, hint in _ERROR_HINTS:
        if needle in lowered:
            return hint
    return ""


def _error_signature(feedback: str) -> str:
    """Hatanin 'aynı hata mi' karsilastirmasi için sadelestirilmis imzasi.

    Satır numaralari ve degisken değerleri degisse bile aynı koke sahip hatalar
    aynı imzayi verir; böylece dongude ilerleme olup olmadigini anlariz.
    """
    line = _first_line(feedback, 300)
    # Yol, satir numarasi ve tirnak icindeki degerleri sabitle
    line = re.sub(r"[A-Za-z]:\[^\s\"']+", "<yol>", line)
    line = re.sub(r"line \d+", "line N", line)
    line = re.sub(r"\d+", "N", line)
    return line.strip().lower()


def _first_line(text: str, limit: int = 160) -> str:
    line = (text or "").strip().splitlines()
    if not line:
        return ""
    last = line[-1].strip()
    return last[:limit] + ("..." if len(last) > limit else "")
