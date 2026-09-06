# -*- coding: utf-8 -*-
"""Birim testleri: HardwareProfiler modülü."""
import unittest
from ai_data_studio.core.hardware_profiler import (
    HardwareProfile,
    profile_hardware,
    format_hardware_report,
    TIER_ULTRA_LOW,
    TIER_MID,
    TIER_HIGH,
    TIER_ENTERPRISE,
    MODEL_1_5B,
    MODEL_7B,
    MODEL_14B,
)


class TestHardwareProfiler(unittest.TestCase):
    def test_profile_hardware_fields(self):
        prof = profile_hardware()
        self.assertIsInstance(prof, HardwareProfile)
        self.assertGreater(prof.ram_total_gb, 0)
        self.assertGreater(prof.cpu_physical_cores, 0)
        self.assertGreater(prof.cpu_logical_cores, 0)
        self.assertIn(prof.hardware_tier, [TIER_ULTRA_LOW, TIER_MID, TIER_HIGH, TIER_ENTERPRISE])
        self.assertIn(prof.execution_mode, ["gpu_cuda", "gpu_metal", "cpu_only"])
        self.assertTrue(len(prof.recommended_model) > 0)
        self.assertGreater(prof.recommended_row_limit, 1000)

    def test_to_dict(self):
        prof = profile_hardware()
        d = prof.to_dict()
        self.assertIn("cpu_name", d)
        self.assertIn("ram_total_gb", d)
        self.assertIn("hardware_tier", d)
        self.assertIn("recommended_model", d)

    def test_format_hardware_report(self):
        rep = format_hardware_report()
        self.assertIn("DONANIM PROFİLİ VE MODEL TAVSİYE RAPORU", rep)
        self.assertIn("İşlemci (CPU):", rep)
        self.assertIn("Sistem RAM:", rep)


if __name__ == "__main__":
    unittest.main()
