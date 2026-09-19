# Contributing to AI Synthetic Data Studio & Validator

Thank you for your interest in contributing to **AI Synthetic Data Studio & Validator**! We welcome bug reports, feature suggestions, documentation improvements, and pull requests from developers, researchers, and data scientists worldwide.

Please take a moment to review this document to ensure smooth collaboration.

---

## 📜 Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before participating in discussions or submitting code.

---

## 🛠️ 1. Development Setup

### Prerequisites
- **Python 3.10, 3.11, or 3.12**
- **Git**
- Optional: **Ollama** installed locally (for local-first model testing)

### Step-by-Step Environment Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/BurakYildizGameDev/ai-data-studio.git
   cd ai-data-studio
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows PowerShell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install -e ".[dev]"
   ```

---

## 🏛️ 2. Core Architectural Rules

This project enforces strict design rules to guarantee thread safety, process isolation, and cross-platform reliability. Automated tests enforce these rules via static AST checks:

1. **GUI & Database Isolation:**
   - GUI components **must never** import `sqlite3` or connect directly to `app_state.db`.
   - All state queries and checkpoints must flow through `StateManager`.
   - Background threads communicate with the UI via the thread-safe `ui_queue` and polling.

2. **File I/O and Encodings:**
   - **Always** specify `encoding="utf-8"` when reading or writing text files (`open`, `to_csv`, `to_json`, etc.).
   - Use the centralized helpers in `config.py` (`read_text`, `write_text`, `read_json`, `write_json`).

3. **Matplotlib & UI Thread Safety:**
   - Never import interactive Matplotlib backends (`FigureCanvasTkAgg`).
   - Use `matplotlib.use("Agg")` and render charts to in-memory buffers displayed as `CTkImage`.

4. **Sandbox Code Execution:**
   - User or LLM-generated code must run inside the subprocess sandbox (`AstSandbox`) with AST import allowlisting and watchdog memory/time limits.
   - **Never** execute untrusted Python code directly using `exec()` or `eval()` in the host process.

5. **Relational Validation Order:**
   - Relational integrity repair **must run after** single-table cleaning, never before.
   - The Discriminator cleans single tables first (`validator.run_validation()`), then `relational_validator.validate_relationships()` runs across foreign key pairs.

6. **Tests Never Touch User Data:**
   - The test suite redirects `AIDATASTUDIO_DATA_DIR` to a temporary directory (`ai_data_studio/tests/conftest.py`), keeping `app_state.db` and output artifacts isolated.
   - Never write to `config.APP_DATA_DIR` assuming it is disposable outside fixtures.

---

## 🧪 3. Running Tests & Quality Checks

Before submitting any code, verify that all tests and lint checks pass:

```bash
# Run the entire test suite (469+ unit & integration tests)
pytest ai_data_studio/tests -v --tb=short

# Run specific engine tests
pytest ai_data_studio/tests/test_parametric_engine.py
pytest ai_data_studio/tests/test_time_series_engine.py
pytest ai_data_studio/tests/test_dirty_data_engine.py
pytest ai_data_studio/tests/test_hardware_profiler.py
pytest ai_data_studio/tests/test_feature_expander.py

# Run static architecture rules test
pytest ai_data_studio/tests/test_gui.py -k TestArchitectureRules

# Run syntax & hygiene check
ruff check .
```

---

## 🌿 4. Git & Pull Request Workflow

We follow standard GitHub flow and Conventional Commits.

1. **Create a topic branch:**
   ```bash
   git checkout -b feature/my-awesome-feature
   # or
   git checkout -b fix/resolve-pandas-categorical-bug
   ```

2. **Write Clean, Tested Code:**
   - Include unit tests for every new feature or bug fix.
   - Maintain PEP 8 style and explicit type annotations.

3. **Commit with Conventional Messages:**
   - `feat(engine): add tweedie distribution vectorization`
   - `fix(validator): resolve categorical dtype mutation in dirty engine`
   - `docs(readme): update live status badges and benchmark results`
   - `test(profiler): add test case for apple silicon MPS detection`

4. **Push and Open a Pull Request:**
   - Push your branch: `git push origin feature/my-awesome-feature`
   - Open a PR against `main`.
   - Provide a concise description of the changes, referencing any related issues.
   - Ensure the automated GitHub Actions CI tests pass (green checkmark).

---

## 💡 5. Submitting Issues & Feature Requests

- **Bug Reports:** Provide your OS, Python version, hardware specs (GPU/CPU/RAM), steps to reproduce, and the complete traceback.
- **Feature Requests:** Explain the motivation, proposed API / design, and potential trade-offs.

---

## 📄 6. Licensing of Contributions

This project is **source-available, not open source**. The code is published under the
[PolyForm Noncommercial License 1.0.0](LICENSE), and the maintainer additionally sells
commercial licences and Pro/Enterprise keys on top of it. That arrangement only holds
together if every line in the repository can be offered on both tracks — so contributions
come with terms. Please read this section before opening a pull request.

**By submitting a contribution, you agree that:**

1. **It is yours to give.** The contribution is your own original work, or you have the
   right to submit it. If an employer holds rights to work you do, you have their approval
   to contribute it here.

2. **You grant a licence broad enough to sell.** You grant the project maintainer a
   perpetual, worldwide, non-exclusive, royalty-free, irrevocable and sublicensable licence
   to use, reproduce, modify, publish, distribute and **commercially license** your
   contribution — in whole or in part, on its own or in a derivative work — including under
   the commercial and Pro/Enterprise terms set out in [LICENSE](LICENSE).

3. **You keep your copyright.** This is a licence, not a transfer of ownership. You remain
   the author, and you stay free to use your own contribution anywhere else, on any terms.

4. **You grant a patent licence.** You grant the same perpetual, worldwide, royalty-free
   and irrevocable licence under any patent claims you own that your contribution
   necessarily infringes.

5. **It comes as is.** Except where the law requires otherwise, you provide the
   contribution without warranties or conditions of any kind.

If you would rather not agree to these terms, that is entirely reasonable — open an issue
describing the change instead of a pull request. The idea is still welcome, and it can be
implemented independently.

Thank you for helping make AI Synthetic Data Studio the premier synthetic data toolkit!
