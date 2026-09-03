"""İzole sandbox yürütme, güvenlik denetimi, zaman aşımı ve bellek watchdog testleri."""
import threading
import unittest

from ai_data_studio.core.generator import (
    ExecutionResult,
    SecurityError,
    execute_in_sandbox,
    sanity_check,
    static_import_check,
)
from ai_data_studio.core.schema_contract import SchemaContract
from ai_data_studio.tests.test_schema_contract import SAMPLE

GOOD_CODE = """
import numpy as np
import pandas as pd


def generate_data(n_rows, seed):
    rng = np.random.default_rng(seed)
    age = np.clip(rng.normal(28, 8, n_rows), 13, 65).astype(int)
    income = np.clip(rng.normal(45000, 20000, n_rows) + (age - 28) * 900, 0, 500000)
    ad_duration_s = rng.integers(5, 61, n_rows)
    watch_time_s = ad_duration_s * rng.beta(2, 2, n_rows)
    clicked = rng.random(n_rows) < 0.05
    return pd.DataFrame({
        "age": age,
        "income": income,
        "ad_duration_s": ad_duration_s,
        "watch_time_s": watch_time_s,
        "clicked": clicked,
    })
"""


class TestStaticImportCheck(unittest.TestCase):
    def test_allowed_imports_pass(self):
        static_import_check("import pandas as pd\nimport numpy\nfrom faker import Faker\n")

    def test_os_import_rejected(self):
        with self.assertRaises(SecurityError) as ctx:
            static_import_check("import os\nos.system('dir')\n")
        self.assertIn("os", str(ctx.exception))

    def test_subprocess_import_rejected(self):
        with self.assertRaises(SecurityError):
            static_import_check("from subprocess import run\n")

    def test_socket_import_rejected(self):
        with self.assertRaises(SecurityError):
            static_import_check("import socket\n")

    def test_eval_rejected(self):
        with self.assertRaises(SecurityError) as ctx:
            static_import_check("x = eval('1+1')\n")
        self.assertIn("eval", str(ctx.exception))

    def test_dunder_import_rejected(self):
        with self.assertRaises(SecurityError):
            static_import_check("__import__('os').system('dir')\n")

    def test_open_rejected(self):
        with self.assertRaises(SecurityError):
            static_import_check("f = open('secrets.txt')\n")

    def test_subclasses_escape_rejected(self):
        with self.assertRaises(SecurityError):
            static_import_check("cls = ().__class__.__bases__[0].__subclasses__()\n")

    def test_syntax_error_reported(self):
        with self.assertRaises(SecurityError) as ctx:
            static_import_check("def broken(:\n    pass\n")
        self.assertIn("parse edilemedi", str(ctx.exception))


class TestSandboxExecution(unittest.TestCase):
    def test_valid_code_runs_and_returns_dataframe(self):
        result = execute_in_sandbox(GOOD_CODE, n_rows=5000, seed=42, timeout=90)
        self.assertTrue(result.success, msg=result.traceback)
        self.assertEqual(result.row_count, 5000)
        self.assertEqual(
            list(result.dataframe.columns),
            ["age", "income", "ad_duration_s", "watch_time_s", "clicked"],
        )

    def test_reproducible_with_same_seed(self):
        a = execute_in_sandbox(GOOD_CODE, n_rows=1000, seed=42, timeout=90)
        b = execute_in_sandbox(GOOD_CODE, n_rows=1000, seed=42, timeout=90)
        self.assertTrue(a.success and b.success)
        self.assertEqual(a.dataframe["age"].tolist(), b.dataframe["age"].tolist())

    def test_different_seed_gives_different_data(self):
        a = execute_in_sandbox(GOOD_CODE, n_rows=1000, seed=1, timeout=90)
        b = execute_in_sandbox(GOOD_CODE, n_rows=1000, seed=2, timeout=90)
        self.assertTrue(a.success and b.success)
        self.assertNotEqual(a.dataframe["age"].tolist(), b.dataframe["age"].tolist())

    def test_forbidden_import_never_executes(self):
        with self.assertRaises(SecurityError):
            execute_in_sandbox("import os\n\ndef generate_data(n, s):\n    os.system('dir')\n")

    def test_runtime_error_is_captured_not_raised(self):
        code = "def generate_data(n_rows, seed):\n    raise ValueError('bilerek patlatildi')\n"
        result = execute_in_sandbox(code, n_rows=10, timeout=60)
        self.assertFalse(result.success)
        self.assertIn("bilerek patlatildi", result.traceback)

    def test_missing_entrypoint_is_reported(self):
        code = "import pandas as pd\n\ndef yanlış_isim(n, s):\n    return pd.DataFrame()\n"
        result = execute_in_sandbox(code, n_rows=10, timeout=60)
        self.assertFalse(result.success)
        self.assertIn("generate_data", result.traceback)

    def test_non_dataframe_return_is_reported(self):
        code = "def generate_data(n_rows, seed):\n    return [1, 2, 3]\n"
        result = execute_in_sandbox(code, n_rows=10, timeout=60)
        self.assertFalse(result.success)
        self.assertIn("DataFrame", result.traceback)

    def test_infinite_loop_times_out(self):
        code = (
            "def generate_data(n_rows, seed):\n"
            "    total = 0\n"
            "    while True:\n"
            "        total += 1\n"
        )
        result = execute_in_sandbox(code, n_rows=10, timeout=5)
        self.assertFalse(result.success)
        self.assertEqual(result.killed_reason, "timeout")
        self.assertIn("Zaman aşımı", result.traceback)

    def test_memory_hog_is_killed(self):
        code = (
            "import numpy as np\n"
            "import pandas as pd\n"
            "\n"
            "def generate_data(n_rows, seed):\n"
            "    blocks = []\n"
            "    for _ in range(400):\n"
            "        blocks.append(np.ones((8_000_000,), dtype=np.float64))\n"
            "    return pd.DataFrame({'a': [1]})\n"
        )
        result = execute_in_sandbox(code, n_rows=10, timeout=60, memory_limit_mb=400)
        self.assertFalse(result.success)
        self.assertIn("Bellek limiti", result.killed_reason)

    def test_cancel_event_stops_execution(self):
        code = (
            "def generate_data(n_rows, seed):\n"
            "    total = 0\n"
            "    while True:\n"
            "        total += 1\n"
        )
        cancel = threading.Event()
        threading.Timer(1.5, cancel.set).start()
        result = execute_in_sandbox(code, n_rows=10, timeout=60, cancel_event=cancel)
        self.assertFalse(result.success)
        self.assertIn("iptal", result.killed_reason.lower())


class TestSanityCheck(unittest.TestCase):
    def setUp(self):
        self.schema = SchemaContract.from_dict({**SAMPLE, "row_count_target": 5000})
        self.result: ExecutionResult = execute_in_sandbox(
            GOOD_CODE, n_rows=5000, seed=42, timeout=90
        )
        self.assertTrue(self.result.success, msg=self.result.traceback)

    def test_conforming_data_has_no_issues(self):
        self.assertEqual(sanity_check(self.result.dataframe, self.schema), [])

    def test_missing_column_detected(self):
        df = self.result.dataframe.drop(columns=["income"])
        issues = sanity_check(df, self.schema)
        self.assertTrue(any("Eksik kolonlar" in i for i in issues))

    def test_extra_column_detected(self):
        df = self.result.dataframe.copy()
        df["fazladan"] = 1
        issues = sanity_check(df, self.schema)
        self.assertTrue(any("fazladan" in i for i in issues))

    def test_row_shortfall_detected(self):
        df = self.result.dataframe.head(100)
        issues = sanity_check(df, self.schema)
        self.assertTrue(any("Satır sayısı çok düşük" in i for i in issues))

    def test_deliberate_noise_is_not_flagged(self):
        """Mimari geregi üretilen veri %10-20 gurultu icerir; onu ayiklamak
        Discriminator'in işi, sanity_check bunu şema ihlali saymamali."""
        df = self.result.dataframe.copy()
        df.loc[df.index[:750], "age"] = 200        # %15 aykiri deger
        self.assertEqual(sanity_check(df, self.schema), [])

    def test_systematic_range_error_detected(self):
        """Sınır ihlali gurultu bandini asarsa (olceklendirme hatası) yakalanmali."""
        df = self.result.dataframe.copy()
        df.loc[df.index[:2000], "age"] = 200       # %40 - kasitli gurultu olamaz
        issues = sanity_check(df, self.schema)
        self.assertTrue(any("max sinirinin" in i for i in issues))

    def test_target_ratio_violation_detected(self):
        df = self.result.dataframe.copy()
        df["clicked"] = True
        issues = sanity_check(df, self.schema)
        self.assertTrue(any("True orani" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
