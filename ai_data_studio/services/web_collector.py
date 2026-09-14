# -*- coding: utf-8 -*-
"""Web Veri Toplayıcı (Web Collector & Extractor).

Kullanıcının verdiği arama sorgusu veya doğrudan URL üzerinden web'den gerçek
örnek veriler toplar, metni temizler ve LLM aracılığıyla yapılandırılmış küçük
bir referans (seed) DataFrame'e dönüştürür.

Bu referans veri:
  1. Şema üretimi (Schema Contract) için gerçek dünya dağılımları ve kolon ilhamı sağlar.
  2. Generator kod üretimi için gerçekçi değer aralıkları sunar.
  3. Discriminator aşamasında Kolmogorov-Smirnov (KS) dağılım testine zemin oluşturur.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..core.schema_contract import extract_json_block
from ..i18n import t
from .llm_base import BaseLLMClient

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_S = 15
MAX_WEB_TEXT_CHARS = 16000


def is_url(text: str) -> bool:
    """Verilen metnin doğrudan bir web adresi olup olmadığını kontrol eder."""
    t = (text or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def clean_html(raw_html: str) -> str:
    """HTML etiketlerini, script, style ve gürültü bloklarını temizler."""
    if not raw_html:
        return ""
    # script, style, noscript, svg, header, footer bloklarini temizle
    cleaned = re.sub(
        r"<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>",
        " ",
        raw_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # HTML yorumlarini kaldir
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    # Tagleri boslukla degistir
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # HTML entity'lerini coz (&amp; -> &)
    cleaned = html.unescape(cleaned)
    # Coklu bosluklari duzenle
    lines = []
    for line in cleaned.splitlines():
        line = " ".join(line.split())
        if len(line) > 20:  # cok kisa/onemsiz satirlari filtrele
            lines.append(line)
    return "\n".join(lines)


def fetch_url_content(url: str, timeout: int = DEFAULT_TIMEOUT_S) -> str:
    """Belirtilen URL'den HTML ceker ve temiz metin dondurur."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return clean_html(raw)
    except Exception as exc:
        log.warning("URL okunamadı (%s): %s", url, exc)
        return ""


def search_duckduckgo(
    query: str, max_results: int = 3, timeout: int = DEFAULT_TIMEOUT_S
) -> List[Dict[str, str]]:
    """DuckDuckGo HTML uzerinden harici anahtar gerektirmeden web aramasi yapar."""
    params = urllib.parse.urlencode({"q": query, "b": ""})
    search_url = "https://html.duckduckgo.com/html/?" + params
    req = urllib.request.Request(
        search_url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "tr,en;q=0.8"},
    )
    results: List[Dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html_text = resp.read().decode("utf-8", errors="replace")

        # HTML sonuclardan link, baslik ve snippet cikar
        matches = re.findall(
            r'<a[^>]+class="result__snippet"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        for link, snippet in matches[:max_results]:
            actual_url = link
            parsed = urllib.parse.urlparse(link)
            if "uddg=" in parsed.query:
                qs = urllib.parse.parse_qs(parsed.query)
                actual_url = qs.get("uddg", [link])[0]
            clean_snip = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({"url": actual_url, "snippet": clean_snip})
    except Exception as exc:
        log.warning("DuckDuckGo araması başarısız: %s", exc)

    return results


def gather_web_text(
    query_or_url: str, max_sources: int = 3, timeout: int = DEFAULT_TIMEOUT_S
) -> Tuple[str, List[str]]:
    """Arama sorgusu veya doğrudan URL'den metin toplar.

    Returns:
        (birlestirilmis_metin, kaynak_listesi)
    """
    query_or_url = query_or_url.strip()
    if is_url(query_or_url):
        text = fetch_url_content(query_or_url, timeout=timeout)
        return text[:MAX_WEB_TEXT_CHARS], [query_or_url]

    # Sorgu ise DuckDuckGo ile arastir
    search_items = search_duckduckgo(query_or_url, max_results=max_sources, timeout=timeout)
    sources: List[str] = []
    text_chunks: List[str] = []

    for item in search_items:
        url = item["url"]
        snip = item.get("snippet", "")
        if snip:
            text_chunks.append(snip)
        sources.append(url)
        # Ilk sayfayi derinlemesine cek
        if len(text_chunks) < 2 and url.startswith("http"):
            page_text = fetch_url_content(url, timeout=timeout)
            if page_text:
                text_chunks.append(page_text[:4000])

    combined = "\n\n---\n\n".join(text_chunks)
    return combined[:MAX_WEB_TEXT_CHARS], sources


def _extract_json_payload(text: str) -> Any:
    """Metinden JSON dizisini veya nesnesini ayiklar (hem [...] hem {...} destekler)."""
    if not text or not text.strip():
        return None
    raw = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        return json.loads(raw)
    except Exception:
        pass

    idx_bracket = raw.find("[")
    idx_brace = raw.find("{")

    if idx_bracket != -1 and (idx_brace == -1 or idx_bracket < idx_brace):
        r_bracket = raw.rfind("]")
        if r_bracket > idx_bracket:
            try:
                return json.loads(raw[idx_bracket : r_bracket + 1])
            except Exception:
                pass

    if idx_brace != -1:
        r_brace = raw.rfind("}")
        if r_brace > idx_brace:
            try:
                return json.loads(raw[idx_brace : r_brace + 1])
            except Exception:
                pass

    return None


def extract_seed_dataframe(
    web_text: str, domain_prompt: str, llm_client: BaseLLMClient, max_rows: int = 30
) -> Optional[pd.DataFrame]:
    """Web'den toplanan ham metinden LLM ile gercek ornek veri tablosu (DataFrame) cikarir."""
    if not web_text or not web_text.strip():
        return None

    system_prompt = (
        "You are an expert data extraction engineer.\n"
        "Your task is to analyze the provided raw web text and extract a realistic, structured "
        "sample tabular dataset representing the target domain.\n\n"
        "Rules:\n"
        "1. Extract up to %d rows of real data points or realistic patterns found in the text.\n"
        "2. Choose clear snake_case column names (e.g. price, brand, rating, year, age).\n"
        "3. Cast numeric columns to proper numbers (not strings with currency symbols).\n"
        "4. Return ONLY a single JSON array of objects: [{\"col_a\": val1, \"col_b\": val2}, ...].\n"
        "5. No markdown fences, no conversational text, no explanations."
        % max_rows
    )

    user_prompt = (
        "Target domain / concept: %s\n\n"
        "Raw web text content:\n\"\"\"\n%s\n\"\"\"\n\n"
        "Extract the structured sample dataset as a JSON array now."
        % (domain_prompt, web_text[:12000])
    )

    try:
        response = llm_client.complete(system_prompt, user_prompt, max_tokens=4000)
        parsed = _extract_json_payload(response)
        if isinstance(parsed, dict) and "data" in parsed and isinstance(parsed["data"], list):
            records = parsed["data"]
        elif isinstance(parsed, list):
            records = parsed
        else:
            log.warning("LLM web verisinden gecerli bir JSON dizisi dondurmedi")
            return None

        if not records or not isinstance(records[0], dict):
            return None

        df = pd.DataFrame(records)
        # Sayisal donusumleri dene
        for col in df.columns:
            try:
                converted = pd.to_numeric(df[col], errors="ignore")
                df[col] = converted
            except Exception:
                pass

        return df
    except Exception as exc:
        log.warning("LLM web verisi cikarma hatasi: %s", exc)
        return None


def collect_web_seed(
    query_or_url: str, domain_prompt: str, llm_client: BaseLLMClient
) -> Tuple[Optional[pd.DataFrame], str]:
    """Uctan uca web'den tohum veri cekme.

    Returns:
        (dataframe_veya_none, kaynak_ozeti)
    """
    raw_text, sources = gather_web_text(query_or_url)
    if not raw_text:
        return None, ""

    df = extract_seed_dataframe(raw_text, domain_prompt, llm_client)
    source_summary = ", ".join(sources[:2]) if sources else query_or_url
    if len(sources) > 2:
        source_summary += " " + t("web.more_sources", count=len(sources) - 2)

    return df, source_summary
