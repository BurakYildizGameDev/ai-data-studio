# Documentation

## [`ENGINEERING_REPORT_TR.md`](ENGINEERING_REPORT_TR.md)

A comprehensive **technical engineering report written in Turkish** covering:

- Architecture deep-dives for the three data engines (ParametricEngine, TimeSeriesEngine, DirtyDataEngine)
- Forensic write-ups of notable bug investigations and fixes
- Head-to-head benchmark results comparing **Gemini 2.5 Pro**, **local Ollama (qwen2.5-coder)**, and **Claude** on identical fraud-detection datasets
- Full unit and integration test run logs (461 tests, 100 % pass rate)
- Design rationale for the Generator–Discriminator pipeline, Correlation Guard, and relational integrity repair

> **Note for non-Turkish readers:** An English translation is planned. In the meantime, the benchmark tables, code listings, and statistical charts are largely self-explanatory. Machine-translation tools (e.g., DeepL) handle the surrounding prose well.
