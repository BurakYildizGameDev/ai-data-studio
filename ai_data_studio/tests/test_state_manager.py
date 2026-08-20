"""Kalıcılık testleri: SQLite okuma/yazma, resume davranışı ve tek bağlantı + lock mekanizması."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from ai_data_studio.core import state_manager as sm
from ai_data_studio.tests.test_schema_contract import SAMPLE


class TestStateManager(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test_state.db"
        self.state = sm.StateManager(self.db)

    def tearDown(self):
        self.state.close()
        self._tmp.cleanup()

    def test_create_and_read_job(self):
        job_id = self.state.create_job("e-ticaret sipariş verisi", provider="anthropic",
                                       model="claude-opus-5", random_seed=7)
        job = self.state.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["prompt"], "e-ticaret sipariş verisi")
        self.assertEqual(job["status"], sm.STATUS_PENDING)
        self.assertEqual(job["random_seed"], 7)

    def test_checkpoint_roundtrip_with_schema(self):
        job_id = self.state.create_job("test")
        self.state.save_checkpoint(
            job_id,
            status=sm.STATUS_RUNNING,
            current_step=45000,
            step_name="Sandbox çalıştırma",
            generated_rows_count=45000,
            schema_metadata=SAMPLE,       # dict verilirse otomatik JSON'a cevrilir
        )
        job = self.state.get_job(job_id)
        self.assertEqual(job["current_step"], 45000)
        self.assertEqual(json.loads(job["schema_metadata"])["domain"], SAMPLE["domain"])
        self.assertEqual(self.state.get_schema(job_id)["row_count_target"], 100000)

    def test_unknown_field_rejected(self):
        job_id = self.state.create_job("test")
        with self.assertRaises(ValueError):
            self.state.save_checkpoint(job_id, definitely_not_a_column=1)

    def test_resume_flow(self):
        """Cokus sonrasi acilis: running -> interrupted -> devam sorusu."""
        job_id = self.state.create_job("kesilecek is")
        self.state.save_checkpoint(job_id, status=sm.STATUS_RUNNING,
                                   current_step=45000, schema_metadata=SAMPLE)
        self.assertIsNone(self.state.get_resumable_job())  # henuz calisiyor

        # Uygulama cokup yeniden aciliyor
        self.assertEqual(self.state.mark_stale_jobs_interrupted(), 1)
        resumable = self.state.get_resumable_job()
        self.assertIsNotNone(resumable)
        self.assertEqual(resumable["job_id"], job_id)
        self.assertEqual(resumable["current_step"], 45000)

    def test_finished_job_is_not_resumable(self):
        job_id = self.state.create_job("biten is")
        self.state.save_checkpoint(job_id, status=sm.STATUS_DONE, schema_metadata=SAMPLE)
        self.state.mark_stale_jobs_interrupted()
        self.assertIsNone(self.state.get_resumable_job())

    def test_cost_tracking(self):
        job_id = self.state.create_job("maliyet")
        cost = self.state.log_llm_call(job_id, "anthropic", "claude-opus-5",
                                       input_tokens=1_000_000, output_tokens=100_000,
                                       purpose="schema")
        self.assertAlmostEqual(cost, 5.0 + 2.5, places=4)
        summary = self.state.get_cost_summary(job_id)
        self.assertEqual(summary["calls"], 1)
        self.assertEqual(summary["input_tokens"], 1_000_000)
        self.assertAlmostEqual(summary["cost_usd"], 7.5, places=4)

    def test_unknown_model_costs_zero(self):
        self.assertEqual(sm.estimate_cost("llama3:8b", 10_000, 10_000), 0.0)

    def test_validation_report_roundtrip(self):
        job_id = self.state.create_job("rapor")
        self.state.save_report(job_id, {"rows_in": 100, "rows_out": 70})
        self.assertEqual(self.state.get_report(job_id)["rows_out"], 70)

    def test_list_and_delete(self):
        ids = [self.state.create_job("job %d" % i) for i in range(3)]
        self.assertEqual(len(self.state.list_jobs()), 3)
        self.state.delete_job(ids[0])
        self.assertEqual(len(self.state.list_jobs()), 2)

    def test_concurrent_writes_do_not_lock(self):
        """Eşzamanlı yazma işlemlerinde 'database is locked' hatası oluşmamalı."""
        job_id = self.state.create_job("eszamanli")
        errors = []

        def worker(offset):
            try:
                for i in range(40):
                    self.state.save_checkpoint(job_id, current_step=offset + i)
                    self.state.get_job(job_id)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i * 1000,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestCorruptionRecovery(unittest.TestCase):
    """Bozuk app_state.db acilista uygulamayi dusurmemeli (Bolum 3.5)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # LIFO: dizin temizligi ilk kaydedilir, boylece EN SON calisir. Windows acik
        # bir SQLite dosyasini silmeye izin vermez; once baglantilar kapanmali.
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "corrupt_state.db"

    def test_malformed_database_is_backed_up_and_recreated(self):
        # Once gecerli bir DB olustur, sonra icini bozarak "disk image is malformed"
        # durumunu birebir tekrarla.
        first = sm.StateManager(self.db)
        first.create_job("bozulmadan onceki is")
        first.close()

        raw = bytearray(self.db.read_bytes())
        raw[4096:8192] = bytes(min(4096, max(0, len(raw) - 4096)))
        self.db.write_bytes(bytes(raw))

        state = sm.StateManager(self.db)          # patlamamali
        self.addCleanup(state.close)

        self.assertIsNotNone(state.recovered_backup_path)
        self.assertTrue(Path(state.recovered_backup_path).exists())
        # Temiz bir DB ile devam edilebiliyor; eski gecmis yedekte.
        self.assertEqual(state.list_jobs(), [])
        new_id = state.create_job("kurtarma sonrasi is")
        self.assertEqual(state.get_job(new_id)["prompt"], "kurtarma sonrasi is")

    def test_healthy_database_reports_no_recovery(self):
        state = sm.StateManager(self.db)
        self.addCleanup(state.close)
        self.assertIsNone(state.recovered_backup_path)
        self.assertFalse(list(Path(self._tmp.name).glob("*.corrupt_*")))

    def test_garbage_file_is_recovered(self):
        """SQLite dosyasi bile olmayan bir cop dosya da acilisi dusurmemeli."""
        self.db.write_bytes(b"bu bir sqlite dosyasi degil" * 100)
        state = sm.StateManager(self.db)
        self.addCleanup(state.close)
        self.assertIsNotNone(state.recovered_backup_path)
        self.assertEqual(state.list_jobs(), [])


class TestDataDirIsolation(unittest.TestCase):
    """Testler kullanicinin canli veri dizinine asla yazmamali (Bolum 3.5)."""

    def test_app_data_dir_is_redirected_to_temp(self):
        from ai_data_studio import config

        data_dir = Path(config.APP_DATA_DIR).resolve()
        self.assertEqual(data_dir, Path(os.environ["AIDATASTUDIO_DATA_DIR"]).resolve())

        # Gercek kullanici dizini disinda olmali.
        live_root = Path(os.getenv("LOCALAPPDATA") or Path.home()) / config.APP_NAME
        self.assertNotEqual(data_dir, live_root.resolve())
        # Varsayilan StateManager da oraya dusmeli.
        self.assertEqual(Path(config.DB_PATH).parent.resolve(), data_dir)

    def test_singleton_state_manager_uses_temp_dir(self):
        state = sm.get_state_manager()
        self.assertEqual(
            Path(state.db_path).parent.resolve(),
            Path(os.environ["AIDATASTUDIO_DATA_DIR"]).resolve(),
        )


if __name__ == "__main__":
    unittest.main()
