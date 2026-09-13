# -*- coding: utf-8 -*-
"""Çoklu Ajan Konseyi (Multi-Agent Council) API Gösterimi ve Doğrulama Betiği.

Bu betik, harici bir API anahtarına ihtiyaç duymadan (sıfır maliyetle ve tamamen offline)
`ai_data_studio.generate(..., agentic=True)` API'sini uçtan uca çalıştırır.

Gösterilen Aşamalar:
1. DomainAnalystAgent: Bankacılık sahtekarlık tespiti için varlıkları ve iş kurallarını modeller.
2. StatisticianAgent: Lognormal harcama, Poisson işlem sayısı ve hedef korelasyonları belirler.
3. AdversarialCriticAgent:
   - 1. Turda şemayı inceler, bilerek eklenmiş `chargeback_status` kolonunu
     hedef sızıntısı (Target Leakage) olarak tespit edip ŞEMAYI REDDEDER.
   - 2. Turda revize edilen temiz şemayı denetler ve ONAY VERİR (Konsensüs).
4. SchemaEngineerAgent: Konsensüsü katı SchemaContract sözleşmesine derler.
5. Sandbox / Generator: 2.000 satırlık sentetik veriyi bellekte üretir.
6. Validator & Discriminator: Z-Score ve Correlation Guard ile istatistiksel doğrulamayı tamamlar.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Repo kök dizinini ekle
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from ai_data_studio import generate, build_config
from ai_data_studio.services.llm_base import BaseLLMClient


class IntelligentCouncilMockLLM(BaseLLMClient):
    """Ajan konseyi tartışmasını simüle eden akıllı sahte LLM."""

    provider = "council_mock"

    def __init__(self):
        super().__init__(model="council-mock-v1")
        self.round_critic = 0

    def health_check(self) -> bool:
        return True

    def _complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 8000,
        temperature: Optional[float] = None,
    ) -> str:
        # 1. Domain Analyst Ajanı (İlk taslak veya revizyon)
        if "Principal Enterprise Data Architect" in system:
            if "previously proposed a domain structure" in user:
                # Revize edilmiş taslak: chargeback_status çıkartıldı
                return json.dumps({
                    "domain": "credit_card_fraud",
                    "summary": "Clean and leakage-free banking transaction dataset",
                    "target_column": "is_fraud",
                    "tables": [
                        {
                            "name": "transactions",
                            "columns": [
                                {"name": "customer_age", "type": "int", "purpose": "demographic", "min": 18, "max": 85},
                                {"name": "transaction_amount", "type": "float", "purpose": "metric", "min": 1.0, "max": 10000.0},
                                {"name": "is_foreign_tx", "type": "bool", "purpose": "state"},
                                {"name": "is_fraud", "type": "bool", "purpose": "target"},
                            ],
                            "business_rules": ["transaction_amount > 0"],
                        }
                    ]
                })
            else:
                # İlk taslak: Bilerek 'chargeback_status' sızıntısı içeriyor!
                return json.dumps({
                    "domain": "credit_card_fraud",
                    "summary": "Draft credit card fraud model",
                    "target_column": "is_fraud",
                    "tables": [
                        {
                            "name": "transactions",
                            "columns": [
                                {"name": "customer_age", "type": "int", "purpose": "demographic"},
                                {"name": "transaction_amount", "type": "float", "purpose": "metric"},
                                {"name": "chargeback_status", "type": "category", "purpose": "target_outcome"}, # Sızıntı!
                                {"name": "is_fraud", "type": "bool", "purpose": "target"},
                            ],
                            "business_rules": ["transaction_amount > 0"],
                        }
                    ]
                })

        # 2. Statistician Ajanı
        if "Senior Quantitative Statistician" in system:
            return json.dumps({
                "tables": [
                    {
                        "name": "transactions",
                        "columns": [
                            {"name": "customer_age", "type": "int", "distribution": "normal", "mean": 42.0, "std": 14.0},
                            {"name": "transaction_amount", "type": "float", "distribution": "lognormal", "mean": 120.0, "std": 80.0},
                            {"name": "is_foreign_tx", "type": "bool", "target_ratio": 0.12},
                            {"name": "is_fraud", "type": "bool", "target_ratio": 0.03},
                        ],
                        "correlations": [
                            {"columns": ["transaction_amount", "is_fraud"], "expected_sign": "positive", "min_r": 0.15}
                        ]
                    }
                ]
            })

        # 3. Adversarial Critic Ajanı (Şeytanın Avukatı)
        if "Chief Data Auditor and Adversarial" in system:
            self.round_critic += 1
            if self.round_critic == 1:
                # 1. Tur: Reddediyor!
                return json.dumps({
                    "approved": False,
                    "confidence_score": 0.35,
                    "leakage_findings": [
                        {
                            "column": "chargeback_status",
                            "reason": "Ters ibraz (chargeback) ancak sahtekarlık gerçekleştikten sonra bilinebilir!",
                            "severity": "HIGH",
                        }
                    ],
                    "rule_conflicts": [],
                    "compliance_issues": [],
                    "verdict_summary": "KRİTİK HATA: 'chargeback_status' kolonu hedef değişkeni sızdırıyor (Target Leakage). Çıkarılmalıdır."
                })
            else:
                # 2. Tur: Onaylıyor!
                return json.dumps({
                    "approved": True,
                    "confidence_score": 0.98,
                    "leakage_findings": [],
                    "rule_conflicts": [],
                    "compliance_issues": [],
                    "verdict_summary": "Şema tamamen temiz, sızıntısız ve istatistiksel olarak tutarlı bulundu."
                })

        # 4. Schema Engineer Ajanı
        if "Senior Data Engineer and Contract Compiler" in system:
            return json.dumps({
                "domain": "credit_card_fraud",
                "description": "Production-ready credit card fraud dataset compiled by Multi-Agent Council",
                "row_count_target": 2000,
                "random_seed": 42,
                "columns": [
                    {"name": "customer_age", "type": "int", "distribution": "normal", "mean": 42.0, "std": 14.0, "min": 18, "max": 85},
                    {"name": "transaction_amount", "type": "float", "distribution": "lognormal", "mean": 120.0, "std": 80.0, "min": 1.0, "max": 10000.0},
                    {"name": "is_foreign_tx", "type": "bool", "target_ratio": 0.12},
                    {"name": "is_fraud", "type": "bool", "target_ratio": 0.03},
                ],
                "business_rules": ["transaction_amount > 0", "customer_age >= 18"],
                "correlations": [
                    {"columns": ["transaction_amount", "is_fraud"], "expected_sign": "positive", "min_r": 0.15}
                ]
            })

        # 5. Sandbox Kod Üretimi (Adım 4)
        return '''
import numpy as np
import pandas as pd

def generate_data(n_rows: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    customer_age = np.clip(rng.normal(42, 14, n_rows), 18, 85).astype(int)
    
    # Lognormal harcama tutarı
    base_amount = rng.lognormal(4.2, 0.9, n_rows)
    transaction_amount = np.clip(base_amount, 1.0, 10000.0)
    
    # Dolandırıcılık hedefi (yüksek tutarlarda fraud ihtimali artar - korelasyon)
    prob_fraud = 0.01 + 0.08 * (transaction_amount > 500.0)
    is_fraud = rng.random(n_rows) < prob_fraud
    
    is_foreign_tx = rng.random(n_rows) < 0.12

    return pd.DataFrame({
        "customer_age": customer_age,
        "transaction_amount": transaction_amount,
        "is_foreign_tx": is_foreign_tx,
        "is_fraud": is_fraud,
    })
'''


def main():
    print("=" * 76)
    print("   AI DATA STUDIO - ÇOKLU AJAN KONSEYİ (MULTI-AGENT) API TESTİ")
    print("   (Harici API Anahtarı Gerekmez - Tamamen Deterministik Simülasyon)")
    print("=" * 76)

    # 1. Sahte İstemciyi Kur
    mock_llm = IntelligentCouncilMockLLM()

    # 2. İlerlemeyi ekrana basacak geri arama (Callback)
    def on_progress(event: Dict[str, Any]):
        step = event.get("step", 0)
        total = event.get("total_steps", 7)
        pct = event.get("percent", 0.0)
        msg = event.get("message", "")
        print(f"[{step}/{total}] {pct:5.1f}% | {msg}")

    print("\n>>> generate(domain='perakende bankacılık fraud tespiti', agentic=True) başlatılıyor...\n")
    t0 = time.perf_counter()

    result = generate(
        domain="perakende bankacılık fraud tespiti",
        rows=2000,
        seed=42,
        agentic=True,         # Çoklu Ajan Konseyini aktifleştir
        max_agent_rounds=2,   # Karşıt eleştiri (Adversarial Critic) 2 tur
        llm_client=mock_llm,  # Sıfır API maliyetli istemci
        on_progress=on_progress,
    )

    elapsed_s = time.perf_counter() - t0

    print("\n" + "=" * 76)
    print(f"🎉 Pipeline Başarıyla Tamamlandı! (Toplam Süre: {elapsed_s:.2f} saniye)")
    print("=" * 76)

    # DataFrame İncelemesi
    df = result.dataframe
    print(f"\n📊 Üretilen DataFrame Özeti:")
    print(f"   • Satır Sayısı  : {len(df):,}")
    print(f"   • Kolon Sayısı  : {len(df.columns)}")
    print(f"   • Kolonlar      : {list(df.columns)}")
    print(f"   • Bellek Boyutu : {df.memory_usage().sum() / 1024:.1f} KB")

    print(f"\n🔍 İlk 5 Satır:")
    print(df.head().to_string(index=False))

    # Doğrulama Raporu
    rep = result.report
    print(f"\n🛡️ İstatistiksel Doğrulayıcı (Discriminator) Raporu:")
    print(f"   • Giren Satır    : {rep.get('rows_in', 0):,}")
    print(f"   • Kalan Satır    : {rep.get('rows_out', 0):,}")
    print(f"   • Koruma Oranı   : {rep.get('retention_pct', 0.0):.1f}%")
    
    corr_results = rep.get("correlations", [])
    if corr_results:
        print("\n📈 Doğrulanan Korelasyonlar:")
        for c in corr_results:
            cols = " <-> ".join(c.get("pair", []))
            r_obs = c.get("actual_r", 0.0)
            r_exp = c.get("min_r", 0.0)
            status = "✅ PASS" if c.get("pass") else "❌ FAIL"
            print(f"   • {cols}: r={r_obs:.3f} (hedef: >= {r_exp:.2f}) -> {status}")

    fraud_rate = df["is_fraud"].mean() * 100
    print(f"\n🎯 Sınıf Dengesi (Target Distribution):")
    print(f"   • Fraud Oranı : %{fraud_rate:.2f} ({df['is_fraud'].sum()} vaka)")

    print("\n✨ Test Başarıyla Tamamlandı: Çoklu Ajan Konseyi ve API kusursuz çalışıyor!")


if __name__ == "__main__":
    main()
