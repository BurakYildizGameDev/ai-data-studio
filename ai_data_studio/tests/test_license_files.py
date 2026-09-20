# -*- coding: utf-8 -*-
"""Depo kökündeki lisans dosyaları yerinde mi?

Proje ikili lisanslama (dual-licensing) modeli kullanıyor: ticari olmayan
kullanım `LICENSE` (PolyForm Noncommercial 1.0.0), ticari kullanım ve imzalı
denetim katmanı `LICENSE-COMMERCIAL.md` ile lisanslanıyor. İkisinden biri
yanlışlıkla silinir ya da yeniden adlandırılırsa satış sayfası da README de
var olmayan bir dosyaya bağlanır; bu testler o sessiz kopmayı yakalar.
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NONCOMMERCIAL_LICENSE = REPO_ROOT / "LICENSE"
COMMERCIAL_LICENSE = REPO_ROOT / "LICENSE-COMMERCIAL.md"


class TestLicenseFiles(unittest.TestCase):
    """Her iki lisans dosyası da kökte ve okunabilir olmalı."""

    def test_noncommercial_license_exists(self):
        self.assertTrue(NONCOMMERCIAL_LICENSE.is_file(),
                        "Kökte LICENSE yok: %s" % NONCOMMERCIAL_LICENSE)
        self.assertIn("PolyForm Noncommercial License 1.0.0",
                      NONCOMMERCIAL_LICENSE.read_text(encoding="utf-8"))

    def test_commercial_license_exists(self):
        self.assertTrue(COMMERCIAL_LICENSE.is_file(),
                        "Kökte LICENSE-COMMERCIAL.md yok: %s" % COMMERCIAL_LICENSE)

    def test_commercial_license_grants_commercial_use(self):
        """Ticari EULA'nın varlık sebebi bu ifade - metinden düşmemeli."""
        text = COMMERCIAL_LICENSE.read_text(encoding="utf-8")
        self.assertIn("commercial use", text.lower())

    def test_commercial_license_is_marked_as_draft(self):
        """Hukuki inceleme bitene kadar taslak ibaresi başta durmalı."""
        first_line = COMMERCIAL_LICENSE.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first_line.strip(), "<!-- DRAFT: LEGAL REVIEW REQUIRED -->")

    def test_commercial_license_avoids_irrevocable(self):
        """Geri alınamaz ("irrevocable") bir taahhüt verilmiyor: ihlal ve ters
        ibra durumlarında anahtarın iptal edilebilmesi gerekiyor."""
        text = COMMERCIAL_LICENSE.read_text(encoding="utf-8")
        self.assertNotIn("irrevocable", text.lower())

    def test_readme_links_both_licenses(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("(LICENSE)", readme)
        self.assertIn("LICENSE-COMMERCIAL.md", readme)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
