"""Tek bir kolon çifti için korelasyon: ``pearson``, ``spearman`` ve ``kendall``.

Doğrulayıcı ile parametrik motor AYNI ölçüyü kullanmalı: motor kopulayı bu
fonksiyonla kalibre eder, doğrulayıcı sonucu bununla denetler. Önceden ikisi de
``kendall`` kuralını sessizce Pearson ile ölçüyordu; Gauss kopulasında
tau = (2/pi) asin(r) < r olduğundan gerçek Kendall ölçümü kuralı düşürürdü.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

__all__ = ["KENDALL_MAX_ROWS", "latent_from_target", "pair_correlation"]

# scipy'nin Kendall tau-b'si O(n log n); yine de milyon satırda motorun kalibrasyon
# döngüsünü yavaşlatmasın diye sabit tohumlu bir örneklem üzerinde ölçülür.
KENDALL_MAX_ROWS = 50_000


def pair_correlation(a: Any, b: Any, method: str = "pearson") -> float:
    """İki dizinin korelasyonu; eksik satırlar atılır, hesaplanamazsa ``nan``."""
    x = pd.Series(np.asarray(a, dtype=float))
    y = pd.Series(np.asarray(b, dtype=float))
    mask = x.notna() & y.notna()
    x, y = x[mask], y[mask]
    if len(x) < 3:
        return float("nan")
    if method == "kendall":
        from scipy.stats import kendalltau

        if len(x) > KENDALL_MAX_ROWS:
            idx = np.random.default_rng(0).choice(len(x), KENDALL_MAX_ROWS, replace=False)
            x, y = x.iloc[idx], y.iloc[idx]
        with np.errstate(invalid="ignore", divide="ignore"):
            return float(kendalltau(x.to_numpy(), y.to_numpy())[0])
    return float(x.corr(y, method="spearman" if method == "spearman" else "pearson"))


def latent_from_target(target: float, method: str = "pearson") -> float:
    """Hedef korelasyonu Gauss kopulasının latent normal korelasyonuna çevirir.

    Sıra ölçüleri için bilinen dönüşümler: Spearman ``rho_s = (6/pi) asin(r/2)``,
    Kendall ``tau = (2/pi) asin(r)``. Pearson hedefi de sıra ölçeğinden başlatılır
    (marjinaller normal değilse zaten kalibrasyon turu düzeltir).
    """
    if method == "kendall":
        latent = np.sin(np.pi * target / 2.0)
    else:
        latent = 2.0 * np.sin(np.pi * target / 6.0)
    return float(np.clip(latent, -0.99, 0.99))
