# -*- coding: utf-8 -*-
"""Modelsiz (şablon) üretim yolu.

Ollama'sı, Claude Code oturumu ve API anahtarı olmayan bir kullanıcı önceden
hiçbir şey üretemiyordu: parametrik motor sözleşmeyi derleyebiliyor ama
sözleşmeyi yazacak bir model yoktu. Buradaki testler o yolun gerçekten hiçbir
sağlayıcıya gitmediğini doğrular.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_data_studio import templates
from ai_data_studio.core import orchestrator
from ai_data_studio.core.dataset_contract import DatasetContract
from ai_data_studio.core.orchestrator import PipelineConfig
from ai_data_studio.core.state_manager import StateManager


class TestTemplateCatalogue(unittest.TestCase):
    """Paketle gelen şablonlar okunabilir ve geçerli sözleşme olmalı."""

    def test_every_bundled_template_parses_as_a_contract(self):
        entries = templates.list_templates()
        self.assertGreaterEqual(len(entries), 3)
        for entry in entries:
            with self.subTest(template=entry["name"]):
                contract = DatasetContract.from_dict(
                    templates.load_template(entry["name"]))
                root = contract.table(contract.root_table)
                self.assertTrue(root.columns)
                self.assertEqual(len(root.columns), entry["columns"])

    def test_the_catalogue_carries_what_the_ui_shows(self):
        for entry in templates.list_templates():
            with self.subTest(template=entry["name"]):
                self.assertTrue(entry["domain"])
                self.assertTrue(entry["description"])
                self.assertGreater(entry["rows"], 0)

    def test_an_unknown_name_raises_rather_than_returning_something(self):
        with self.assertRaises(KeyError):
            templates.template_json("does-not-exist")

    def test_a_traversing_name_cannot_reach_outside_the_package(self):
        """Ad dogrudan dosya adina giriyor; ``../`` ile disari cikilmamali."""
        for hostile in ("../../config", "..\\..\\config", "/etc/passwd"):
            with self.subTest(name=hostile):
                with self.assertRaises(KeyError):
                    templates.template_json(hostile)

    def test_template_json_round_trips(self):
        raw = templates.template_json("ecommerce_orders")
        self.assertEqual(json.loads(raw), templates.load_template("ecommerce_orders"))


class TestOfflineContractRun(unittest.TestCase):
    """Hazır sözleşmeyle koşu: hiçbir sağlayıcıya gidilmemeli."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state = StateManager(db_path=Path(self.temp_dir.name) / "jobs.db")
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.state.close)

    def _run(self, cfg):
        """Sonuc jeneratorun DONUS degeri; ilerleme satirlari yield ediliyor."""
        iterator = orchestrator.run_pipeline(cfg, state=self.state)
        while True:
            try:
                next(iterator)
            except StopIteration as stop:
                return stop.value

    def _config(self, **kwargs):
        defaults = dict(
            domain_prompt="",
            contract_json=templates.template_json("ecommerce_orders"),
            row_count=120,
            random_seed=7,
            export_formats=["csv"],
            write_outputs=False,
            output_dir=Path(self.temp_dir.name),
        )
        defaults.update(kwargs)
        return PipelineConfig(**defaults)

    def test_a_template_run_never_builds_an_llm_client(self):
        with mock.patch.object(orchestrator, "_build_llm_client",
                               side_effect=AssertionError("modele gidildi")) as never:
            result = self._run(self._config())

        never.assert_not_called()
        self.assertEqual(len(result.dataframe.columns), 8)
        self.assertGreater(len(result.dataframe), 0)
        self.assertEqual(result.cost.get("total_calls", 0), 0)

    def test_the_run_uses_the_requested_row_count_not_the_template_one(self):
        result = self._run(self._config(row_count=150))

        # Dogrulama birkac satir eleyebilir; sablondaki 10.000 ile karistirilmamali.
        self.assertLessEqual(len(result.dataframe), 150)
        self.assertGreater(len(result.dataframe), 100)

    def test_the_engine_falls_back_to_parametric_even_if_llm_was_asked(self):
        with mock.patch.object(orchestrator, "_build_llm_client",
                               side_effect=AssertionError("modele gidildi")):
            result = self._run(self._config(engine=orchestrator.ENGINE_LLM))

        self.assertEqual(result.report["engines"]["generation"],
                         orchestrator.ENGINE_PARAMETRIC)

    def test_a_contract_file_of_the_users_own_is_accepted(self):
        contract = {
            "domain": "Sensor readings",
            "row_count_target": 50,
            "columns": [
                {"name": "sensor_id", "type": "int", "min": 1, "max": 20},
                {"name": "temperature_c", "type": "float", "min": -40, "max": 85},
            ],
        }
        result = self._run(self._config(contract_json=json.dumps(contract)))

        self.assertEqual(list(result.dataframe.columns), ["sensor_id", "temperature_c"])

    def test_an_unreadable_contract_is_reported_clearly(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(self._config(contract_json="{not json"))
        self.assertIn("contract", str(ctx.exception).lower())

    def test_features_that_need_a_model_are_refused_up_front(self):
        """Sessizce yok saymak yerine neden calismadigini soylemeli."""
        for kwargs in ({"project_prompt": "churn modeli"},
                       {"agentic": True},
                       {"use_web_seed": True, "web_seed_query": "x"},
                       {"push_to_hub": "user/dataset"}):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    self._run(self._config(**kwargs))


class TestTemplateCli(unittest.TestCase):
    """``--list-templates`` / ``--template`` / ``--schema-file``."""

    def test_listing_templates_exits_zero_and_names_them(self):
        with mock.patch("sys.stdout") as out:
            code = orchestrator.main(["--list-templates"])

        printed = " ".join(str(call) for call in out.write.call_args_list)
        self.assertEqual(code, 0)
        self.assertIn("ecommerce_orders", printed)

    def test_an_unknown_template_is_refused_before_anything_runs(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(orchestrator.main(["--template", "nope"]), 2)

    def test_template_and_schema_file_together_are_refused(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(
                orchestrator.main(["--template", "ecommerce_orders",
                                   "--schema-file", "x.json"]), 2)

    def test_a_template_needs_no_domain_argument(self):
        """Modelsiz kullanicidan ayrica alan tarifi istemek yolu kapatirdi."""
        captured = {}

        def fake_run(cfg, *args, **kwargs):
            captured["cfg"] = cfg
            return iter(())

        with mock.patch.object(orchestrator, "run_pipeline", side_effect=fake_run), \
             mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            orchestrator.main(["--template", "credit_risk", "--rows", "10"])

        self.assertTrue(captured["cfg"].contract_json)
        self.assertEqual(captured["cfg"].domain_prompt, "credit_risk")


if __name__ == "__main__":
    unittest.main()
