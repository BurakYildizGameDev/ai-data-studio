# Contributing to AI Synthetic Data Studio

Thank you for your interest in contributing to **AI Synthetic Data Studio & Validator**! We welcome bug reports, feature suggestions, documentation improvements, and code contributions.

---

## 1. Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/BurakYildizGameDev/ai-data-studio.git
   cd ai-data-studio
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows PowerShell
   python -m venv .venv
   .venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies in editable mode:**
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

---

## 2. Core Architectural Rules

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
   - Use `matplotlib.use("Agg")` and render charts to in-memory buffers rendered as `CTkImage`.

4. **Sandbox Code Execution:**
   - User or LLM-generated code must run inside the subprocess sandbox with AST import allowlisting and watchdog memory/time limits. Never use `exec()` or `eval()` directly in the host process.

5. **Relational Validation Order:**
   - Relational integrity repair **must run after** single-table cleaning, never before.
   - The Discriminator removes rows table by table; dropping a parent row orphans its
     children, so foreign keys can only be trusted once every table has been cleaned.
   - Concretely: run `validator.run_validation()` for each table first, then
     `relational_validator.validate_relationships()` on the cleaned set.

6. **Tests Never Touch User Data:**
   - The suite redirects `AIDATASTUDIO_DATA_DIR` to a temporary directory
     (`ai_data_studio/tests/conftest.py`), so `app_state.db`, outputs and settings
     stay isolated from the real application data.
   - Never construct a `StateManager()` without a path in a test, and never write to
     `config.APP_DATA_DIR` assuming it is disposable outside that fixture.

---

## 3. Running the Test Suite

Before submitting any Pull Request, ensure that all tests pass:

```bash
# Run full unit & integration test suite
python -m unittest discover -s ai_data_studio/tests -t .

# Run static architecture checks
python -m unittest ai_data_studio.tests.test_gui.TestArchitectureRules
```

---

## 4. Code Style & Standards

- Follow **PEP 8** guidelines.
- Use explicit type annotations where possible.
- Write clear, concise docstrings explaining the architectural intent.
- Ensure all commit messages and documentation are professional and descriptive.
