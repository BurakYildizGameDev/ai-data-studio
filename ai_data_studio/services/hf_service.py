"""HuggingFace Hub entegrasyonu - arama, referans seed indirme, push ve dataset card oluşturma.

İşlevler:
  * search_datasets()      - query bazlı dataset arama
  * load_seed_dataframe()  - örnek satırları pandas DataFrame olarak çekme
  * push_dataset()         - doğrulanmış veriyi kullanıcının namespace'ine yükleme
  * build_dataset_card()   - model ile (veya yerel şablonla) README.md üretimi

Tüm Hub API çağrıları tenacity exponential backoff ile güvenceye alınır.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .. import config

log = logging.getLogger(__name__)

__all__ = [
    "HFError",
    "HFNotConfiguredError",
    "search_datasets",
    "load_seed_dataframe",
    "build_dataset_card",
    "push_dataset",
]


class HFError(RuntimeError):
    """HuggingFace islemi başarısız."""


class HFNotConfiguredError(HFError):
    """HF token eksik (yalnızca push için zorunlu)."""


class HFRetryableError(HFError):
    """Geçici hata - backoff ile yeniden denenmeli."""


_hf_retry = retry(
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(4),
    retry=retry_if_exception_type(HFRetryableError),
    reraise=True,
)


def _classify(exc: Exception) -> HFError:
    """Hub istisnasini kalıcı/geçici olarak siniflandirir."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return HFRetryableError("HF geçici hata (%s): %s" % (status, exc))
    if status in (401, 403):
        return HFNotConfiguredError("HF yetkilendirme hatası (%s): %s" % (status, exc))
    name = type(exc).__name__
    if name in ("ConnectionError", "Timeout", "ReadTimeout", "HfHubHTTPError"):
        return HFRetryableError("HF bağlantı hatası: %s" % exc)
    return HFError("HF hatası: %s" % exc)


def get_token() -> Optional[str]:
    """keyring -> HF_TOKEN -> HUGGING_FACE_HUB_TOKEN -> huggingface-cli login token'i."""
    credential = config.resolve_credential("huggingface")
    if credential.value:
        return credential.value
    if credential.kind == config.KIND_SDK_DEFAULT:
        try:
            from huggingface_hub import get_token as hub_get_token
            return hub_get_token()
        except Exception:
            return None
    return None


def _api(token: Optional[str] = None):
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:  # pragma: no cover
        raise HFError("`huggingface_hub` paketi kurulu değil") from exc
    return HfApi(token=token or get_token())


# --------------------------------------------------------------------------- #
# Arama
# --------------------------------------------------------------------------- #
@_hf_retry
def search_datasets(query: str, limit: int = 15,
                    token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query bazli dataset arama. İndirme sayisina gore sirali sonuç dondurur."""
    if not query or not query.strip():
        return []
    try:
        results = list(_api(token).list_datasets(
            search=query.strip(), limit=limit, sort="downloads", direction=-1
        ))
    except Exception as exc:
        raise _classify(exc) from exc

    out: List[Dict[str, Any]] = []
    for info in results:
        out.append({
            "id": info.id,
            "downloads": getattr(info, "downloads", 0) or 0,
            "likes": getattr(info, "likes", 0) or 0,
            "tags": list(getattr(info, "tags", []) or [])[:12],
            "last_modified": str(getattr(info, "last_modified", "") or ""),
        })
    return out


# --------------------------------------------------------------------------- #
# Seed veri indirme
# --------------------------------------------------------------------------- #
@_hf_retry
def load_seed_dataframe(dataset_id: str, max_rows: int = 2000,
                        config_name: Optional[str] = None,
                        split: Optional[str] = None,
                        token: Optional[str] = None) -> pd.DataFrame:
    """Bir HF dataset'inden ornek satirlari DataFrame olarak stream eder.

    Tüm veri seti indirilmez; streaming ile yalnızca max_rows satır cekilir.
    """
    try:
        import datasets as hf_datasets
    except ImportError as exc:  # pragma: no cover
        raise HFError("`datasets` paketi kurulu değil") from exc

    hf_token = token or get_token()

    if config_name is None:
        try:
            names = hf_datasets.get_dataset_config_names(dataset_id, token=hf_token)
            config_name = names[0] if names else None
        except Exception as exc:
            log.debug("Config adları alınamadı (%s): %s", dataset_id, exc)

    if split is None:
        try:
            splits = hf_datasets.get_dataset_split_names(
                dataset_id, config_name=config_name, token=hf_token
            )
            split = "train" if "train" in splits else (splits[0] if splits else "train")
        except Exception as exc:
            log.debug("Split adları alınamadı (%s): %s", dataset_id, exc)
            split = "train"

    try:
        stream = hf_datasets.load_dataset(
            dataset_id, name=config_name, split=split, streaming=True, token=hf_token
        )
        rows = list(stream.take(max_rows))
    except Exception as exc:
        raise _classify(exc) from exc

    if not rows:
        raise HFError("Dataset boş veya okunamadı: %s" % dataset_id)

    df = pd.DataFrame(rows)
    # Ic ice (dict/list) kolonlar sema ilhami icin kullanissiz - atiliyor.
    nested = [c for c in df.columns
              if df[c].map(lambda v: isinstance(v, (dict, list))).any()]
    if nested:
        log.info("Ic ice kolonlar atlandı: %s", nested)
        df = df.drop(columns=nested)

    log.info("Seed veri yüklendi: %s (%s satır, %d kolon)",
             dataset_id, format(len(df), ","), len(df.columns))
    return df


# --------------------------------------------------------------------------- #
# Dataset card (Bolum 6.5)
# --------------------------------------------------------------------------- #
def build_dataset_card(schema, report: Optional[Dict[str, Any]] = None,
                       llm_client=None, repo_id: str = "") -> str:
    """push_to_hub oncesi README.md üretir.

    LLM verilmisse şema bazli bir kart yazdirilir; LLM yoksa veya çağrı başarısız
    olursa deterministik bir sablona düşülür (push hiçbir zaman kart yuzunden kirilmaz).
    """
    stats = _card_stats(schema, report)
    if llm_client is not None:
        try:
            card = llm_client.generate_dataset_card(schema, stats)
            if card and card.lstrip().startswith("---"):
                return card
            log.warning("LLM dataset card'i YAML front matter ile baslamiyor, sablona dusuluyor")
        except Exception as exc:
            log.warning("LLM dataset card uretemedi (%s), sablona dusuluyor", exc)
    return _fallback_card(schema, stats, repo_id)


def _card_stats(schema, report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    report = report or {}
    return {
        "rows_generated": report.get("rows_in"),
        "rows_after_validation": report.get("rows_out"),
        "retention_pct": report.get("retention_pct"),
        "business_rules": report.get("business_rules", []),
        "correlations": report.get("correlations", []),
        "distributions": report.get("distributions", {}),
        "column_stats": report.get("column_stats", {}),
        "random_seed": getattr(schema, "random_seed", None),
    }


def _fallback_card(schema, stats: Dict[str, Any], repo_id: str = "") -> str:
    rows_out = stats.get("rows_after_validation")
    size_cat = _size_category(rows_out or 0)
    lines: List[str] = [
        "---",
        "license: mit",
        "language:",
        "  - en",
        "tags:",
        "  - synthetic",
        "  - ai-generated",
        "  - %s" % schema.domain,
        "size_categories:",
        "  - %s" % size_cat,
        "---",
        "",
        "# %s (synthetic)" % schema.domain.replace("_", " ").title(),
        "",
        "## Dataset Summary",
        "",
        "**This dataset is fully synthetic and machine-generated.** It contains no real "
        "observations and no personal data. It was produced by AI Synthetic Data Studio: an "
        "LLM designed a schema contract for the domain, wrote a Python generator for it, the "
        "generator ran in a sandbox, and a statistical validation pipeline stripped noise, "
        "outliers and business-rule violations from the result.",
        "",
    ]
    if schema.description:
        lines += [schema.description, ""]

    lines += ["## Columns", "", "| Column | Type | Description |", "|---|---|---|"]
    for col in schema.columns:
        lines.append("| `%s` | %s | %s |" % (col.name, col.type, col.description or "-"))
    lines.append("")

    lines += [
        "## Generation Method",
        "",
        "1. **Schema contract** - an LLM analysed the domain and emitted a strict JSON schema "
        "(columns, ranges, distributions, business rules, expected correlations).",
        "2. **Code generation** - the LLM wrote a vectorised `generate_data(n_rows, seed)` "
        "function; a self-healing loop fed execution errors and schema mismatches back to the "
        "model until the output conformed.",
        "3. **Sandboxed execution** - the generator ran in an isolated subprocess with an import "
        "allowlist, a wall-clock timeout and a memory watchdog.",
        "4. **Validation** - duplicates, schema-bound violations, business-rule violations, "
        "Z-score outliers (|Z| > 3) and IsolationForest anomalies were removed.",
        "",
        "Random seed: `%s` - regenerating with the same seed and generator reproduces the data."
        % stats.get("random_seed"),
        "",
        "## Validation",
        "",
    ]
    if rows_out:
        lines.append("- Rows generated: **%s**" % format(stats.get("rows_generated") or 0, ","))
        lines.append("- Rows after validation: **%s**" % format(rows_out, ","))
        lines.append("- Retention: **%s%%**" % stats.get("retention_pct"))
    for rule in stats.get("business_rules", []):
        if rule.get("status") == "applied":
            lines.append("- Rule `%s` - %s violating rows removed"
                         % (rule["rule"], format(rule.get("violations", 0), ",")))
    for corr in stats.get("correlations", []):
        lines.append("- Correlation %s: r = %s (expected %s, min %s) - %s"
                     % ("/".join(corr["pair"]), corr.get("actual_r"),
                        corr.get("expected_sign"), corr.get("min_r"),
                        "PASS" if corr.get("pass") else "FAIL"))
    dist = stats.get("distributions") or {}
    if not dist.get("skipped") and dist.get("columns"):
        lines.append("- Kolmogorov-Smirnov vs. reference data: %s/%s columns matched (p > 0.05)"
                     % (dist.get("passed"), dist.get("total")))
    lines.append("")

    lines += [
        "## Limitations and Intended Use",
        "",
        "- This is **synthetic data**. Do not treat any row as a real observation.",
        "- It is intended for prototyping, load testing, schema design, teaching and "
        "augmenting real datasets - not for safety-critical decisions, clinical or financial "
        "conclusions, or as evidence about real populations.",
        "- Distributions reflect an LLM's prior about the domain plus explicit statistical "
        "constraints; they may encode the model's biases and can diverge from reality.",
        "- The validation pipeline removes statistical outliers, which makes the data cleaner "
        "than reality. Real-world tails are under-represented by construction.",
        "",
    ]
    if repo_id:
        lines += ["```python",
                  "from datasets import load_dataset",
                  "",
                  'ds = load_dataset("%s")' % repo_id,
                  "```", ""]
    lines.append("_Generated with [AI Synthetic Data Studio](https://github.com/) - "
                 "Generator-Discriminator architecture._")
    return "\n".join(lines)


def _size_category(n: int) -> str:
    for bound, label in ((1_000, "n<1K"), (10_000, "1K<n<10K"), (100_000, "10K<n<100K"),
                         (1_000_000, "100K<n<1M")):
        if n < bound:
            return label
    return "1M<n<10M"


# --------------------------------------------------------------------------- #
# Push (Bolum 6.5)
# --------------------------------------------------------------------------- #
@_hf_retry
def push_dataset(df: pd.DataFrame, repo_id: str, schema,
                 report: Optional[Dict[str, Any]] = None,
                 llm_client=None, private: bool = True,
                 token: Optional[str] = None,
                 commit_message: str = "Add synthetic dataset") -> str:
    """Temiz veriyi kullanicinin HF namespace'ine yukler ve dataset card ekler.

    Returns:
        Yuklenen dataset'in URL'i.
    """
    hf_token = token or get_token()
    if not hf_token:
        raise HFNotConfiguredError(
            "HuggingFace token bulunamadı. Ayarlar sekmesinden girin veya "
            "HF_TOKEN ortam değişkenini tanımlayın."
        )
    if df is None or df.empty:
        raise HFError("Yuklenecek veri boş")

    try:
        import datasets as hf_datasets
    except ImportError as exc:  # pragma: no cover
        raise HFError("`datasets` paketi kurulu değil") from exc

    try:
        dataset = hf_datasets.Dataset.from_pandas(df.reset_index(drop=True))
        dataset.push_to_hub(repo_id, private=private, token=hf_token,
                            commit_message=commit_message)
    except Exception as exc:
        raise _classify(exc) from exc

    # Dataset card - basarisiz olsa bile push'u gecersiz kilmaz.
    try:
        card = build_dataset_card(schema, report, llm_client, repo_id)
        _api(hf_token).upload_file(
            path_or_fileobj=card.encode("utf-8"),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="dataset",
            token=hf_token,
            commit_message="Add dataset card",
        )
    except Exception as exc:
        log.error("Dataset card yuklenemedi (veri yüklendi): %s", exc)

    url = "https://huggingface.co/datasets/%s" % repo_id
    log.info("Dataset yüklendi: %s", url)
    return url
