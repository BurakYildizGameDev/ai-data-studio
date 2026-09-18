# -*- coding: utf-8 -*-
"""Hazır Schema Contract şablonları — hiçbir model gerektirmeyen giriş yolu.

Pipeline sözleşmeyi normalde bir LLM'e yazdırır. Ollama kurulu değilse, Claude
Code oturumu yoksa ve elde API anahtarı da yoksa kullanıcı hiçbir şey
üretemiyordu: parametrik motor sözleşmeyi derleyebiliyor ama sözleşmenin
kendisini kimse yazmıyordu.

Buradaki dosyalar o boşluğu doldurur. Her biri geçerli bir Schema Contract'tır;
``PipelineConfig.contract_json`` ile verildiğinde pipeline [1] servis kontrolünü
ve [2] şema üretimini tamamen atlar, parametrik motorla veriyi derler. Ağ yok,
anahtar yok, kurulum yok.

Şablonlar başlangıç noktasıdır, hedef değil: kullanıcı ``--schema-file`` ile
kendi sözleşmesini de verebilir, ya da bir şablonu dışa aktarılan
``*_schema.json`` üzerinden düzenleyip yeniden çalıştırabilir.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

__all__ = [
    "TEMPLATE_DIR",
    "list_templates",
    "load_template",
    "template_json",
]

TEMPLATE_DIR = Path(__file__).resolve().parent


def _template_path(name: str) -> Path:
    """Şablon adını dosya yoluna çevirir.

    Ad doğrudan dosya adına giriyor; ``../`` ile paket dışına çıkılmasın diye
    yalnızca ada göre eşleşen dosyalar kabul edilir (bkz. K-3).
    """
    clean = str(name or "").strip().lower()
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        if path.stem == clean:
            return path
    raise KeyError(name)


def list_templates() -> List[Dict[str, Any]]:
    """Paketle gelen şablonlar: ``name``, ``domain``, ``columns``, ``description``."""
    entries: List[Dict[str, Any]] = []
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append({
            "name": path.stem,
            "domain": str(data.get("domain", "")),
            "description": str(data.get("description", "")),
            "columns": len(data.get("columns", []) or []),
            "rows": int(data.get("row_count_target", 0) or 0),
        })
    return entries


def template_json(name: str) -> str:
    """Şablonun ham JSON metni (``PipelineConfig.contract_json`` bunu bekler)."""
    return _template_path(name).read_text(encoding="utf-8")


def load_template(name: str) -> Dict[str, Any]:
    """Şablonu sözlük olarak okur."""
    return json.loads(template_json(name))
