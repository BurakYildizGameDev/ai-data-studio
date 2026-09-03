"""Programatik (kutuphane) API testleri - ai_data_studio.generate / validate.

Tumu offline: gercek LLM cagrisi yerine FakeLLMClient kullanilir.
"""
from __future__ import annotations

import glob
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import pandas as pd

import ai_data_studio
from ai_data_studio import build_config, config, generate, validate
from ai_data_studio.core.orchestrator import PipelineResult
from ai_data_studio.core.schema_contract import SchemaContract
from ai_data_studio.tests.fake_llm import (
    SCHEMA_JSON,
    FakeLLMClient,
    FakeRelationalLLMClient,
    FakePlannerLLMClient,
)


class TestLazyPackageSurface(unittest.TestCase):
    """__init__ tembel yukleme sozlesmesi."""

    def test_public_names_are_listed(self):
        for name in ("generate", "validate", "build_config", "PipelineConfig",
                     "PipelineResult", "run_pipeline", "SchemaContract"):
            self.assertIn(name, ai_data_studio.__all__)
            self.assertIn(name, dir(ai_data_studio))
            self.assertIsNotNone(getattr(ai_data_studio, name))

    def test_unknown_attribute_raises(self):
        with self.assertRaises(AttributeError):
            ai_data_studio.boyle_bir_sey_yok

    def test_bare_import_does_not_pull_pandas(self):
        """`import ai_data_studio` agir bagimliliklari cekmemeli.

        Eager import'a donulurse paket acilisi ~0.3 ms'ten ~345 ms'e cikar;
        bu test o regresyonu yakalar.
        """
        code = (
            "import sys; import ai_data_studio; "
            "print(int('pandas' in sys.modules), "
            "int('ai_data_studio.core.orchestrator' in sys.modules))"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              cwd=str(Path(__file__).resolve().parents[2]))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "0 0")

    def test_version_exposed(self):
        self.assertTrue(ai_data_studio.__version__)


class TestBuildConfig(unittest.TestCase):
    def test_no_export_by_default(self):
        cfg = build_config("x")
        self.assertFalse(cfg.write_outputs)

    def test_output_dir_enables_export(self):
        cfg = build_config("x", output_dir="/tmp/out")
        self.assertTrue(cfg.write_outputs)
        self.assertEqual(cfg.export_formats, ["csv"])

    def test_formats_alone_enables_export(self):
        cfg = build_config("x", formats=["parquet", "JSON"])
        self.assertTrue(cfg.write_outputs)
        self.assertEqual(cfg.export_formats, ["parquet", "json"])

    def test_keyword_passthrough(self):
        cfg = build_config("x", rows=123, seed=7, provider="ollama",
                           contamination=0.05, correlation_guard=False)
        self.assertEqual(cfg.row_count, 123)
        self.assertEqual(cfg.random_seed, 7)
        self.assertEqual(cfg.provider, "ollama")
        self.assertEqual(cfg.contamination, 0.05)
        self.assertFalse(cfg.correlation_guard)

    def test_unknown_keyword_rejected(self):
        with self.assertRaises(TypeError):
            build_config("x", bilinmeyen_parametre=1)


class TestGenerate(unittest.TestCase):
    def test_returns_result_without_writing_files(self):
        default_out = Path(config.OUTPUT_DIR)
        before = set(glob.glob(str(default_out / "*"))) if default_out.exists() else set()

        result = generate("e-commerce orders", rows=3000, provider="ollama",
                          llm_client=FakeLLMClient())

        self.assertIsInstance(result, PipelineResult)
        self.assertIsInstance(result.dataframe, pd.DataFrame)
        self.assertGreater(len(result.dataframe), 0)
        self.assertIn("retention_pct", result.report)
        self.assertIsInstance(result.schema, SchemaContract)
        self.assertTrue(result.code.strip())
        self.assertEqual(result.output_paths, {})

        after = set(glob.glob(str(default_out / "*"))) if default_out.exists() else set()
        self.assertEqual(after - before, set(), "varsayilan cikti dizinine dosya sizdi")

    def test_output_dir_writes_requested_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = generate("e-commerce orders", rows=2000, provider="ollama",
                              llm_client=FakeLLMClient(),
                              output_dir=tmp, formats=["csv"])
            self.assertIn("csv", result.output_paths)
            self.assertNotIn("parquet", result.output_paths)
            # Sema/kod/rapor her zaman eslik eder.
            for kind in ("schema", "code", "report"):
                self.assertIn(kind, result.output_paths)
            for path in result.output_paths.values():
                self.assertTrue(Path(path).exists())

    def test_progress_callback_receives_events(self):
        events = []
        generate("e-commerce orders", rows=1500, provider="ollama",
                 llm_client=FakeLLMClient(), on_progress=events.append)
        self.assertGreater(len(events), 5)
        for key in ("step", "total_steps", "message", "percent"):
            self.assertIn(key, events[0])
        self.assertEqual(events[-1]["step"], events[-1]["total_steps"])

    def test_row_count_is_honoured(self):
        result = generate("e-commerce orders", rows=2500, provider="ollama",
                          llm_client=FakeLLMClient())
        # Validasyon satir eledigi icin hedefin uzerine cikilmamali.
        self.assertLessEqual(len(result.dataframe), 2500)
        self.assertGreater(len(result.dataframe), 0)

    def test_cancel_event_stops_pipeline(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Exception):
            generate("e-commerce orders", rows=1000, provider="ollama",
                     llm_client=FakeLLMClient(), cancel_event=cancel)

    def test_unknown_keyword_rejected(self):
        with self.assertRaises(TypeError):
            generate("x", provider="ollama", llm_client=FakeLLMClient(),
                     boyle_bir_parametre_yok=True)


class TestValidateHelper(unittest.TestCase):
    def setUp(self):
        self.schema = SchemaContract.from_dict(SCHEMA_JSON)
        rng = __import__("numpy").random.default_rng(0)
        n = 2000
        item_count = rng.integers(1, 25, n)
        self.df = pd.DataFrame({
            "customer_age": rng.integers(18, 80, n),
            "basket_value": item_count * 40.0 + rng.normal(0, 30, n).clip(0, None),
            "item_count": item_count,
            "shipping_cost": rng.uniform(0, 20, n),
            "returned": rng.random(n) < 0.08,
        })

    def test_accepts_schema_contract(self):
        clean, report = validate(self.df, self.schema)
        self.assertLessEqual(len(clean), len(self.df))
        self.assertIn("stages", report)

    def test_accepts_dict_and_json(self):
        clean_dict, _ = validate(self.df, SCHEMA_JSON)
        clean_json, _ = validate(self.df, self.schema.to_json())
        self.assertEqual(len(clean_dict), len(clean_json))

    def test_forwards_validator_options(self):
        _, report = validate(self.df, self.schema, correlation_guard=False)
        self.assertFalse(report["correlation_guard"]["enabled"])


class TestRelationalApi(unittest.TestCase):
    """generate(relational=True) - kutuphane arayuzunden cok tablolu uretim."""

    def test_build_config_accepts_relational_keywords(self):
        cfg = build_config("saas", relational=True, max_tables=4, repair_orphans=False)
        self.assertTrue(cfg.relational)
        self.assertEqual(cfg.max_tables, 4)
        self.assertFalse(cfg.repair_orphans)

    def test_defaults_stay_single_table(self):
        cfg = build_config("saas")
        self.assertFalse(cfg.relational)
        self.assertEqual(cfg.max_tables, 6)
        self.assertTrue(cfg.repair_orphans)

    def test_generate_returns_all_tables(self):
        result = generate("saas billing", rows=2000, provider="fake", relational=True,
                          llm_client=FakeRelationalLLMClient())
        self.assertIsInstance(result, PipelineResult)
        self.assertEqual(sorted(result.tables), ["customers", "orders"])
        self.assertIs(result.dataframe, result.tables["customers"])
        self.assertTrue(result.report["relational"]["pass"])
        self.assertEqual(result.contract.root_table, "customers")

    def test_generate_writes_per_table_files_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = generate("saas billing", rows=2000, provider="fake",
                              relational=True, formats=["csv"], output_dir=tmp,
                              llm_client=FakeRelationalLLMClient())
            written = sorted(Path(p).name for p in result.output_paths.values())
            self.assertTrue(any(n.endswith("_customers.csv") for n in written), written)
            self.assertTrue(any(n.endswith("_orders.csv") for n in written), written)
            self.assertTrue(any(n.endswith("_manifest.json") for n in written), written)

    def test_single_table_result_still_exposes_tables(self):
        result = generate("e-commerce orders", rows=3000, provider="ollama",
                          llm_client=FakeLLMClient())
        self.assertEqual(list(result.tables), ["ecommerce_orders"])
        self.assertIsNone(result.report.get("relational"))


class TestProjectApi(unittest.TestCase):
    """generate(project=...) - projeden veri setine, kutuphane arayuzunden."""

    def test_build_config_accepts_project(self):
        cfg = build_config("x", project="churn tahmini")
        self.assertEqual(cfg.project_prompt, "churn tahmini")

    def test_default_has_no_project(self):
        self.assertEqual(build_config("x").project_prompt, "")

    def test_generate_from_project_only(self):
        result = generate(project="abonelerden hangileri ayrilacak", rows=2000,
                          provider="fake", llm_client=FakePlannerLLMClient())
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.target.label(), "customers.churned")
        self.assertEqual(sorted(result.tables), ["customers", "orders"])

    def test_generate_requires_domain_or_project(self):
        with self.assertRaises(TypeError):
            generate()

    def test_plan_excluded_columns_are_not_generated(self):
        result = generate(project="churn", rows=2000, provider="fake",
                          llm_client=FakePlannerLLMClient())
        excluded = {e.column for e in result.plan.excluded_leakage}
        for df in result.tables.values():
            self.assertEqual(excluded & set(df.columns), set())


if __name__ == "__main__":
    unittest.main()
