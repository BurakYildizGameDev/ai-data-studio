# -*- coding: utf-8 -*-
"""English catalog - the default language and the fallback for every other one.

Keys are ASCII and shaped `module.context.short_name`. When you add a key here,
add it to every other catalog too: `tests/test_i18n.py` walks the source with AST
and fails on a key that is used but not defined, or defined here but missing from
a translation.
"""

MESSAGES = {
    # --- Settings view --------------------------------------------------- #
    "settings.keys.title": "API Keys",
    "settings.keys.storage_note": (
        "Keys are stored in the operating system credential store (keyring). "
        "They are never written to a plain-text file."
    ),
    "settings.keys.save": "Save",
    "settings.keys.test": "Test",
    "settings.keys.get_key": "Get a key",
    "settings.keys.placeholder": "(falls back to {env_var} when empty)",
    "settings.keys.defined_source": "Defined - source: {source}",
    "settings.keys.implicit_source": "No key entered, but {source} was found - it will be tried",
    "settings.keys.missing": "Not defined",
    "settings.keys.saved": "Saved to the credential store",
    "settings.keys.keyring_unavailable": "the credential store is unavailable - use an environment variable",
    "settings.keys.save_failed": "Could not be saved: {error}",
    "settings.keys.testing": "Testing...",
    "settings.keys.test_ok": "Connection OK - {detail}",
    "settings.keys.test_failed": "Failed: {error}",

    "settings.oauth.title": "Sign in with OAuth / CLI",
    "settings.oauth.note": (
        "You can sign in through the browser instead of pasting an API key. The "
        "login command runs in its own console window; choose 'Rescan' once it "
        "finishes."
    ),
    "settings.oauth.rescan": "Rescan",
    "settings.oauth.login": "Sign in",
    "settings.oauth.logged_in": "Signed in - {detail}",
    "settings.oauth.not_installed": "{command} is not installed ({hint})",
    "settings.oauth.not_logged_in": "Not signed in",

    "settings.ollama.title": "Ollama (local models)",
    "settings.ollama.checking": "Checking...",
    "settings.ollama.refresh": "Refresh",
    "settings.ollama.open_manager": "Open the model manager",
    "settings.ollama.quick_pull": "Quick pull",
    "settings.ollama.pull": "Pull",
    "settings.ollama.running": "Ollama {version} is running - {count} models installed",
    "settings.ollama.down": "The Ollama daemon is not running. Start it with: ollama serve",
    "settings.ollama.down_host": "The Ollama daemon is not answering at {host}. Start it with: ollama serve",
    "ollama.host.label": "Server address",
    "ollama.host.save": "Save",
    "ollama.host.saved": "Server address saved: {host}",
    "ollama.host.invalid": "That address could not be read: {value}",
    "ollama.host.remote_hint": "Ollama can run on another machine: enter its address (e.g. http://192.168.1.20:11434) and start the daemon there with OLLAMA_HOST=0.0.0.0 ollama serve. Leave the box empty to fall back to the OLLAMA_HOST environment variable.",
    "ollama.install.hint": "Ollama not installed? Download it, install it, then pull a first model from a terminal:",
    "ollama.install.download": "Download Ollama",
    "ollama.copy": "Copy",
    "ollama.copied": "Copied: {text}",

    "settings.defaults.title": "Defaults",
    "settings.defaults.theme": "Theme",
    "settings.defaults.language": "Language",
    "settings.defaults.language_restart": (
        "The language changes the next time you start the application."
    ),
    "settings.defaults.data_dir": "Data directory",

    "settings.cost.title": "LLM Cost Summary",
    # --- Charts ---------------------------------------------------------- #
    "charts.panel.title": "Validation Charts",
    "charts.panel.placeholder": "Charts appear here once a pipeline has run.",
    "charts.panel.empty": "No chart could be drawn.",
    "charts.retention.title": "Validation stages",
    "charts.retention.x_label": "Rows removed",
    "charts.distribution.title": "{column} distribution",
    "charts.distribution.y_label": "Frequency",
    "charts.correlation.title": "Correlation matrix",

    # --- Progress panel -------------------------------------------------- #
    "progress.status.ready": "Ready",
    "progress.status.finished": "Finished",
    "progress.button.start": "Run the pipeline",
    "progress.button.cancel": "Cancel",
    # --- Main window ----------------------------------------------------- #
    "app.tab.pipeline": "Pipeline",
    "app.tab.history": "History",
    "app.tab.settings": "Settings",
    "app.console.ready": "AI Synthetic Data Studio is ready.",
    "app.console.data_dir": "Data directory: {path}",
    "app.console.checkpoint": "Checkpoint saved: step {step}",
    "app.console.db_recovered": (
        "The state database was corrupt and has been rebuilt; the job history was "
        "reset. A backup of the damaged file is at: {path}"
    ),
    "app.resume.title": "Unfinished job",
    "app.resume.message": (
        "Job #{job_id} ({domain}) did not finish.\n\n"
        "Step {step}/7 - {step_name}\nRows generated: {rows}\n\n"
        "Restart it with the same settings?"
    ),
    "app.resume.accept": "Yes, load the settings",
    "app.resume.decline": "No",
    "app.resume.declined": "Job #{job_id} was not resumed.",
    "app.done.separator": "FINISHED",
    "app.done.summary": "Finished - {rows} clean rows",
    "app.done.rows": "Job #{job_id}: {rows_in} raw -> {rows_out} clean rows ({retention}% kept)",
    "app.done.cost": "Cost: ${cost} ({calls} calls, {tokens} tokens)",
    "app.error.separator": "ERROR",
    "app.error.header": "Error",
    "app.error.prefix": "Error: {message}",
    "app.error.no_result": "The pipeline returned no result",
    "app.cancelled.status": "Cancelled",
    "app.cancelled.console": "The pipeline was cancelled.",
    # --- Model selector -------------------------------------------------- #
    "model.provider": "Provider",
    "model.provider.ollama": "Ollama (local)",
    "model.credential": "Credential",
    "model.model": "Model",
    "model.configure": "Configure",
    "model.manage": "Models",
    "model.list.none": "(no model installed)",
    "model.list.loading": "(loading...)",
    "model.auth.api_key": "API key",
    "model.auth.oauth_token": "OAuth token",
    "model.auth.oauth": "OAuth",
    "model.auth.local": "Local - no credential needed",
    "model.auth.missing": "Not configured - {hint}",
    "model.auth.hint_key_only": "use 'Configure' to enter a free API key",
    "model.auth.hint_oauth_unset": "an OAuth session exists but is not selected - press 'Configure'",
    "model.auth.hint_key_or_oauth": "enter a key or sign in with OAuth",
    "model.agy.loading": "Fetching Antigravity CLI models...",
    "model.agy.list_failed": (
        "The Antigravity CLI model list could not be read. Run `agy` in a terminal "
        "and make sure you are signed in."
    ),
    "model.agy.loaded": (
        "Antigravity CLI: {count} models. The agent CLI is slow - a single step can "
        "take minutes."
    ),
    "model.ollama.checking": "Checking Ollama...",
    "model.ollama.installed": (
        "Ollama {version} - {count} models installed ({models}). Use 'Models' to pull another."
    ),
    "model.ollama.no_models": (
        "Ollama {version} is running but no model is installed. Pull one from 'Models'."
    ),
    "model.hardware.recommendation": "Hardware: {tier} - recommended model {model}{note}",
    "model.hardware.not_installed": "(not installed)",
    "model.ready.no_models": "No model available. Pull one from the 'Models' button.",
    "model.ready.pick_model": "Pick a model first.",
    "model.ready.no_credential": (
        "No credential is configured for {provider}. Use 'Configure' to enter an API "
        "key, or sign in with OAuth."
    ),
    # --- History view ---------------------------------------------------- #
    "history.title": "Past Jobs",
    "history.refresh": "Refresh",
    "history.clear": "Clear",
    "history.jobs": "Jobs",
    "history.pick_job": "Pick a job on the left.",
    "history.cleared": "All past jobs were cleared.",
    "history.empty": "No job has been run yet.",
    "history.field.status": "Status",
    "history.field.domain": "Domain",
    "history.field.prompt": "Request",
    "history.field.provider": "Provider",
    "history.field.created": "Created",
    "history.field.updated": "Updated",
    "history.field.step": "Step",
    "history.field.seed": "Random seed",
    "history.field.rows_generated": "Rows generated",
    "history.field.rows_clean": "Clean rows",
    "history.field.cost": "LLM cost",
    "history.field.calls": "{calls} calls",
    "history.field.output": "Output",
    "history.section.error": "ERROR",
    "history.section.schema": "SCHEMA",
    "history.section.validation": "VALIDATION",
    "history.schema.columns": "Columns: {columns}",
    "history.schema.rule": "rule: {rule}",
    "history.validation.rows": "{rows_in} -> {rows_out} rows ({retention}% kept)",
    "history.validation.correlation": "correlation {pair}: r={r} [{verdict}]",
    "history.verdict.pass": "PASS",
    "history.verdict.fail": "FAIL",
    # --- Ollama model manager -------------------------------------------- #
    "ollama.legend": "Green = installed (ready to use)   |   Grey = not installed (can be pulled)",
    "ollama.other_model": "Another model",
    "ollama.manual_placeholder": "full name from ollama.com/library, e.g. llama3.2:3b",
    "ollama.cancel_pull": "Cancel the download",
    "ollama.close": "Close",
    "ollama.list_unavailable": "The model list is unavailable because the daemon is not running.",
    "ollama.daemon_running": "Ollama {version} is running - {count} models installed",
    "ollama.section.installed": "INSTALLED",
    "ollama.section.available": "AVAILABLE",
    "ollama.choose": "Select and use",
    "ollama.delete": "Delete",
    "ollama.deleted": "Deleted: {name}",
    "ollama.delete_failed": "Could not delete: {error}",
    "ollama.need_name": "Enter a model name first.",
    "ollama.already_pulling": "A download is already in progress.",
    "ollama.pulling": "Downloading: {name}",
    "ollama.pulled": "Downloaded: {name}",
    "ollama.pull_failed": "Could not download: {name}",
    "ollama.pull_cancelled": "The download was cancelled.",
    "ollama.cancelling": "Cancelling...",
    # --- Auth dialog ----------------------------------------------------- #
    "auth.title": "{provider} - credential settings",
    "auth.method.api_key": "API key",
    "auth.method.agy": "Antigravity CLI sign-in",
    "auth.method.oauth": "OAuth / CLI sign-in",
    "auth.api.title": "Paste your API key",
    "auth.api.storage_note": (
        "The key goes into the operating system credential store (keyring); it is "
        "never written to a plain-text file."
    ),
    "auth.api.where_to_get": "Get one at: {url}",
    "auth.api.placeholder": "paste the key here",
    "auth.api.show": "Show",
    "auth.api.save_and_test": "Save and test",
    "auth.api.clear": "Delete the stored key",
    "auth.api.need_key": "Paste a key first.",
    "auth.api.saved_testing": "Saved, testing...",
    "auth.api.no_key_url": "No key page is defined for this provider.",
    "auth.api.opened_browser": "Opened in the browser: {url}",
    "auth.api.cleared": "The stored key was deleted.",
    "auth.oauth.title": "Sign in through the browser",
    "auth.oauth.title_agy": "Connect through the Antigravity CLI",
    "auth.oauth.subtitle": (
        "The command below runs in its own console and opens your browser. This "
        "window updates itself once the sign-in completes."
    ),
    "auth.oauth.subtitle_agy": (
        "Your existing Antigravity CLI session is used - no API key, GCP project or "
        "billing required. If you are not signed in, the command below opens in a "
        "console."
    ),
    "auth.oauth.refresh_state": "Refresh status",
    "auth.oauth.test": "Test the connection",
    "auth.oauth.unsupported": "This provider has no CLI sign-in.",
    "auth.oauth.command_missing": "`{command}` was not found. Install it first: {hint}",
    "auth.oauth.launch_failed": "Sign-in could not be started: {error}",
    "auth.oauth.waiting": "Waiting for sign-in...",
    "auth.oauth.console_opened": (
        "A console window opened. Finish the sign-in in your browser - this view "
        "updates itself when you are done."
    ),
    "auth.oauth.success": "Signed in.",
    "auth.oauth.timeout": "The sign-in did not complete (timed out). You can try again.",
    "auth.agy.speed_note": (
        "Note: the Antigravity CLI is an interactive agent and loads its own context "
        "on every call. A single pipeline step can take minutes; prefer the AI Studio "
        "API key if speed matters."
    ),
    "auth.agy.use": "Use the Antigravity CLI",
    "auth.agy.not_installed": "`agy` was not found. Install the Antigravity CLI: {url}",
    "auth.agy.selected": "Antigravity CLI selected. Verifying the session...",
    "auth.current.in_use": "Currently used: {source}",
    "auth.current.missing": (
        "No credential is configured. Enter an API key below, or sign in with OAuth."
    ),
    "auth.test.running": "Testing the connection...",
    "auth.test.ok": "Success - {detail}",
    "auth.test.signed_in_as": "Signed in as: {name}",
    # --- Pipeline view: form --------------------------------------------- #
    "pipeline.mode.domain": "Describe the data",
    "pipeline.mode.project": "Describe the project",
    "pipeline.form.title": "What do you want to generate?",
    "pipeline.example.domain": (
        "Mobile game advertising engagement: age, income, ad duration, watch time "
        "and clicks."
    ),
    "pipeline.example.project": (
        "I want to spot the customers who are about to stop buying from my online "
        "store, so the retention team can send them an offer."
    ),
    "pipeline.hint.domain": (
        "Describe the domain in plain language; the LLM works out the schema itself."
    ),
    "pipeline.hint.project": (
        "Describe your project; the system decides what data it needs, the target "
        "variable, the class balance, which leakage columns to drop, and the "
        "train/test split."
    ),
    "pipeline.rows.label": "Row count",
    "pipeline.rows.label_root": "Root table row count",
    "pipeline.form.seed": "Random seed",
    "pipeline.form.locale": "Faker locale",
    "pipeline.form.formats": "Output formats",
    "pipeline.seed.hf": "Use a HuggingFace reference (seed) dataset",
    "pipeline.seed.hf_placeholder": "HF search query or dataset ID",
    "pipeline.seed.web": "Collect live reference data from the web (search / URL)",
    "pipeline.seed.web_placeholder": "search topic, or a direct https:// URL",
    "pipeline.engine.label": "Generation engine",
    "pipeline.engine.llm": "LLM code generation",
    "pipeline.engine.parametric": "Parametric (fast, no LLM)",
    "pipeline.engine.auto": "Automatic (LLM, else parametric)",
    "pipeline.engine.llm_hint": (
        "The LLM writes a generator in Python and runs it in the sandbox, healing its "
        "own errors. The most flexible path."
    ),
    "pipeline.engine.parametric_hint": (
        "The schema compiles straight to vectors: no LLM code, no sandbox, "
        "milliseconds. Single-table only for now."
    ),
    "pipeline.engine.auto_hint": (
        "Code generation is tried first; if the attempts run out the run does not "
        "fail, it falls back to the parametric engine."
    ),
    "pipeline.engine.time_series": "Add time series and velocity analysis",
    "pipeline.engine.expand_features": "Expand features (ratios, bands, time derivations)",
    "pipeline.engine.dirty": "Inject controlled dirty data (rate %)",
    "pipeline.engine.small_model_switched": "{model} is a small model, so the engine was switched to Parametric: LLM code generation fails with it, and Parametric produces the same data in seconds. You can switch back.",
    "pipeline.engine.small_model_warning": "{model} is a small model: LLM code generation fails with it. Parametric is recommended - Automatic ends up there too, but only after three failed code rounds.",
    "pipeline.relational.enable": "Generate a relational (multi-table) dataset",
    "pipeline.relational.max_tables": "Max tables",
    "pipeline.relational.repair": "Repair orphan foreign keys (otherwise only reported)",
    "pipeline.tab.console": "Console",
    "pipeline.tab.result": "Result",
    "pipeline.tab.charts": "Charts",
    "pipeline.result.empty": "No result yet.",
    "pipeline.result.open_folder": "Open the output folder",
    # --- Result tab ------------------------------------------------------ #
    "result.section.engines": "ENGINES",
    "result.section.relational": "RELATIONAL INTEGRITY",
    "result.section.plan": "PROJECT PLAN",
    "result.section.stages": "CLEANING STAGES",
    "result.section.rules": "BUSINESS RULES",
    "result.section.correlations": "CORRELATION CHECK",
    "result.section.preserved": "PRESERVED ANOMALIES (FRAUD / OUTLIER EXEMPTION)",
    "result.section.distribution": "DISTRIBUTION (KS) TEST",
    "result.section.outputs": "OUTPUT FILES",
    "result.rows_value": "{rows} rows",
    "result.warning": "WARNING: {message}",
    "result.rows_raw": "Raw rows generated",
    "result.rows_validated": "Passed validation",
    "result.retention": "Retention",
    "result.attempts": "Code generation attempts",
    "result.sandbox_seconds": "Sandbox time (s)",
    "result.cost": "Estimated LLM cost",
    "result.rule_violations": "{count} violations",
    "result.distribution.summary": "{passed}/{total} columns match the reference distribution (p > 0.05)",
    "result.charts_failed": "The charts could not be drawn: {error}",
    "result.engines.generation": "Generation",
    "result.engines.time_series": "Time series",
    "result.engines.time_series_value": "{entities} distinct entities, {bursts} velocity bursts",
    "result.engines.time_range": "Range",
    "result.engines.feature_expander": "Feature expansion",
    "result.engines.feature_value": "+{added} columns ({total} total)",
    "result.engines.added_columns": "Added",
    "result.engines.dirty": "Controlled corruption",
    "result.engines.dirty_value": "{rows} rows ({rate}%), AFTER validation",
    "result.engines.dirty_breakdown": "Breakdown",
    "result.engines.dirty_breakdown_value": (
        "missing {missing}, typos {typo}, spikes {spike}, casing/whitespace {casing}"
    ),
    "result.engines.note": "Note",
    "result.engines.stats_note": "column statistics were computed BEFORE corruption",
    "result.relational.verdict": "Verdict",
    "result.relational.failed": "FAILED",
    "result.relational.repair": "Orphan repair",
    "result.relational.repair_off": "OFF (reported only)",
    "result.relational.row_counts": "Table row counts:",
    "result.relational.orphans_removed": "Orphans removed by repair",
    "result.relational.fk": "FK [{relationship}]: {orphans} orphans ({pct}%) {verdict}",
    "result.relational.violation": "VIOLATION",
    "result.relational.cardinality": (
        "Cardinality [{relationship}]: mean {observed} (expected {expected}) {verdict}"
    ),
    "result.relational.deviation": "DEVIATION",
    "result.relational.pk_not_unique": "WARNING: primary key '{pk}' of '{table}' is not unique",
    "result.plan.task_type": "Task type",
    "result.plan.table_count": "Table count",
    "result.plan.target": "Target variable",
    "result.plan.class_balance": "Class balance",
    "result.plan.positive_pct": "positive {pct}%",
    "result.plan.split": "Train/test split",
    "result.plan.reason": "reason: {reason}",
    "result.plan.rationale": "Plan rationale",
    "result.plan.leakage_header": "Leakage columns dropped ({count}):",
    "result.plan.leakage": "Leakage dropped",
    "result.plan.leakage_none": "none",
    # --- Run lifecycle & form validation --------------------------------- #
    "app.status.running": "Running...",
    "app.run.separator": "NEW PIPELINE",
    "app.run.domain": "Domain: {domain}",
    "app.run.parameters": "Provider: {provider} / {model} | {rows} rows | seed {seed}",
    "app.error.already_running": "A pipeline is already running.",
    "app.resume.loaded": (
        "Job #{job_id} settings loaded - press 'Run the pipeline' to run it again with "
        "the same seed."
    ),
    "app.cancel.requested": "Cancellation requested, finishing the current step...",
    "app.cancel.in_progress": "Cancelling...",
    "pipeline.relational.project_mode_note": (
        "In project mode the planner decides how many tables are needed, so the "
        "relational switch is disabled."
    ),
    "pipeline.error.empty_project": "Describe your project first.",
    "pipeline.error.empty_domain": "Write what you want to generate first.",
    "pipeline.error.rows_not_int": "The row count must be a whole number.",
    "pipeline.error.rows_not_positive": "The row count must be positive.",
    "pipeline.error.seed_not_int": "The random seed must be a whole number.",
    "pipeline.error.no_format": "Pick at least one output format.",
    "pipeline.error.dirty_not_number": "The corruption rate must be a number (e.g. 5).",
    "pipeline.error.dirty_range": "The corruption rate must be between 0% and 100%.",
    "pipeline.error.max_tables_not_int": "The table cap must be a whole number.",
    "pipeline.error.max_tables_range": "In relational mode the table count must be between 2 and 12.",
    "pipeline.error.folder_open": "The folder could not be opened: {error}",
    # --- Pipeline steps --------------------------------------------------- #
    "step.1": "Service check",
    "step.2": "Research & schema generation",
    "step.3": "Seed data lookup (HuggingFace)",
    "step.4": "Code generation & self-healing",
    "step.5": "Sandbox execution",
    "step.6": "Validation & cleaning",
    "step.7": "Output & checkpoint",

    # --- Pipeline errors -------------------------------------------------- #
    "pipeline.error.unknown_engine": "Unknown generation engine: {engine} (valid: {valid})",
    "pipeline.error.dirty_rate_range": "dirty_rate must be between 0 and 1, got {value}",
    "pipeline.error.max_tables_planner": "max_tables must be between 1 and {limit}, got {value}",
    "pipeline.error.max_tables_relational": "max_tables must be between 2 and {limit}, got {value}",
    "pipeline.error.unknown_fraud_table": (
        "--fraud-table '{table}' is not in the contract. Valid tables: {tables}"
    ),
    "pipeline.error.unknown_audit_table": (
        "--audit-table '{table}' is not in the contract. Valid tables: {tables} (or 'all')"
    ),
    "pipeline.error.unknown_ts_table": (
        "--ts-table '{table}' is not in the contract. Valid tables: {tables}"
    ),
    "pipeline.error.unknown_expand_table": (
        "--expand-table '{table}' is not in the contract. Valid tables: {tables}"
    ),
    "pipeline.error.unknown_dirty_table": (
        "--dirty-table '{table}' is not in the contract. Valid tables: {tables}"
    ),
    "pipeline.cancelled_by_user": "The pipeline was cancelled by the user",

    # --- Run progress ------------------------------------------------------ #
    "run.checking_provider": "Checking the provider: {provider} / {model}",
    "run.service_ready": "Service ready: {model}",
    "run.provider_model": "Provider: {provider} | Model: {model}",
    "run.seed.hf_searching": "Searching HuggingFace for reference data...",
    "run.seed.loaded": "Seed data loaded: {source} ({rows} rows)",
    "run.seed.columns": "Reference columns ({count}): {columns}",
    "run.seed.none_found": "No suitable seed data found - the schema is designed from scratch",
    "run.seed.web_searching": "Searching and collecting reference data from the web: '{query}'...",
    "run.seed.web_collected": "Reference data collected from the web: {source} ({rows} rows, {columns} columns)",
    "run.seed.extracted_columns": "Extracted reference columns: {columns}",
    "run.seed.web_none": "No usable data could be extracted from the web - the schema is designed from scratch",
    "run.seed.skipped": "No seed data is used (skipped)",
    "run.plan.analysing": "Analysing the project: what data does it need?",
    "run.schema.relational": "The LLM is analysing the domain and writing a relational Dataset Contract...",
    "run.schema.single": "The LLM is analysing the domain and writing a Schema Contract...",
    "run.schema.contract_ready": (
        "Dataset Contract ready: {tables} tables, {relationships} relationships (root table: {root})"
    ),
    "run.schema.ready": "Schema ready: {summary}",
    "run.audit.tables": "Tables to be audited for privacy: {tables}",
    "run.engine.parametric_selected": "Parametric engine selected - code generation and the sandbox are skipped",
    "run.engine.compiled_no_llm": "The schema compiled straight to vectors ({seconds} s, no LLM code)",
    "run.engine.compiled": "The schema compiled straight to vectors ({seconds} s)",
    "run.engine.falling_back": "Falling back to the parametric engine (--engine auto)",
    "run.engine.small_model_warning": "{model} is a small model: LLM code generation fails with it (0 of 3 runs measured on a 1.5B model). --engine parametric produces the same data without the failed code rounds.",
    "run.codegen.writing": "Writing the code that generates the data...",
    "run.codegen.failed_warning": "WARNING: code generation failed ({error})",
    "run.raw.generated": "Raw data generated: {rows} rows ({attempts} attempts, {seconds} s)",
    "run.raw.generated_relational": (
        "Raw data generated: {tables} tables, {rows} rows ({attempts} attempts, {seconds} s)"
    ),
    "run.raw.saved": "Raw data saved: {name} ({size} MB)",
    "run.fraud.injected": (
        "Fraud scenarios injected: {rows} rows (rate: {rate}%, table: {table}, column: {column})"
    ),
    "run.time_series.applied": (
        "Time-series dynamics applied: {entities} distinct entities, {bursts} velocity "
        "bursts, median gap {median} s"
    ),
    "run.time_series.entity_warning": (
        "WARNING: column '{column}' holds {distinct} distinct values across {rows} rows; "
        "velocity metrics are meaningless. Give a column that repeats: --ts-entity-col <column>"
    ),
    "run.features.expanded": "Feature expansion: {added} new columns ({total} total)",
    "run.validation.running": "The discriminator is running...",
    "run.validation.table": "Validating table: {table}",
    "run.validation.done": "Validation finished: {rows_in} -> {rows_out} rows ({retention}% kept)",
    "run.validation.table_rows": "{rows_in} -> {rows_out} rows ({retention}%)",
    "run.relational.checking": "Checking relational integrity ({count} relationships)...",
    "run.relational.repair_disabled": "orphan repair is off (--no-repair-orphans)",
    "run.relational.contract_violated": "the contract is still violated",
    "run.relational.failed": "WARNING: the relational integrity check failed - {reason}",
    "run.dirty.injected": (
        "Controlled corruption injected: {rows} rows ({rate}%) - missing {missing}, "
        "typos {typo}, spikes {spike}, casing/whitespace {casing}"
    ),
    "run.dirty.audit_columns": "Audit-trail columns added: is_corrupted, corruption_details",
    "run.output.writing": "Writing the output files...",
    "run.output.written": "Output written: {kinds}",
    "run.output.skipped": "No output file was written (write_outputs=False)",
    "run.hub.uploading": "Uploading to HuggingFace: {repo}",
    "run.hub.uploaded": "Uploaded: {url}",
    "run.cost.summary": "LLM usage: {calls} calls, {tokens} tokens, ~${cost}",
    "run.finished": "Finished. {rows} clean rows, estimated cost ${cost}",
    "run.finished_relational": "Finished. {tables} tables, {rows} clean rows, estimated cost ${cost}",
    # --- Plan & schema console dump --------------------------------------- #
    "run.plan.ready": "Plan ready: {summary}",
    "run.plan.rationale": "Rationale: {rationale}",
    "run.plan.target": "Target variable: {target}",
    "run.plan.class_balance": "Class balance: positive class {pct}%",
    "run.plan.leakage": "Columns dropped because they would leak ({count}):",
    "run.plan.split": "Train/test split: {kind} - {reason}",
    "run.schema.generation_order": "{tables} tables, generation order: {order}",
    "run.schema.table_line": "Table '{table}' | PK: {pk} | target {rows} rows",
    "run.schema.columns_header": "Declared columns ({count}):",
    "run.schema.spec_range": "range: [{low}, {high}]",
    "run.schema.spec_distribution": "distribution: {distribution}",
    "run.schema.spec_categories": "categories: [{categories}]",
    "run.schema.spec_ratio": "ratio: {pct}%",
    "run.schema.spec_not_null": "not null",
    "run.schema.rules_header": "Business rules ({count}):",
    "run.schema.rule": "Rule: {rule}",
    "run.schema.correlations_header": "Expected correlations ({count}):",
    "run.schema.relationships_header": "Relationships ({count}):",
    "run.schema.relationship": "{label} (mean {mean} per parent; {bounds}{optional})",
    "run.schema.optional": "optional",

    # --- CLI --------------------------------------------------------------- #
    "cli.auth.header": "Credential status",
    "cli.auth.source": "source: {source}",
    "cli.auth.implicit": "no key, but {source} was found - it will be tried",
    "cli.auth.checked": "checked: keyring, {vars}",
    "cli.auth.oauth_logged_in": "OAuth: signed in - {detail}",
    "cli.auth.oauth_missing": "OAuth: {command} is not installed ({hint})",
    "cli.auth.oauth_login": "OAuth: sign in with -> {command}",
    "cli.auth.note": "NOTE:  {note}",
    "cli.auth.ollama_running": "Ollama {version} - {count} models",
    "cli.auth.ollama_down": "the daemon is not running ({host})",
    "cli.auth.none_available": "No provider is usable.",
    "cli.error.domain_and_project": (
        "--domain and --project cannot be combined: either describe the data or "
        "describe the project"
    ),
    "cli.error.domain_or_project": "--domain or --project is required (or use --check-auth)",
    "cli.error.generic": "ERROR: {error}",
    "cli.label.domain": "Domain",
    "cli.label.project": "Project",
    "cli.label.provider": "Provider",
    "cli.label.backend": "(backend: {backend})",
    "cli.label.target": "Target",
    "cli.label.target_value": "{rows} rows, seed {seed}",
    "cli.label.mode": "Mode",
    "cli.label.engine": "Engine",
    "cli.mode.planner": "project planner (up to {limit} tables, the plan decides how many)",
    "cli.mode.relational": "relational (up to {limit} tables, orphan repair: {repair})",
    "cli.on": "on",
    "cli.off": "OFF",
    "cli.engine.time_series": "time series",
    "cli.engine.expand_features": "feature expansion",
    "cli.engine.dirty": "corruption {pct}%",
    "cli.cancelled": "Cancelled.",
    "cli.cancelled_with": "Cancelled: {reason}",
    "cli.summary.job_done": "Job #{job_id} finished.",
    "cli.summary.clean_rows": "Clean rows",
    "cli.summary.clean_rows_value": "{rows_out} / {rows_in} ({retention}% kept)",
    "cli.summary.cost": "Cost",
    "cli.summary.outputs": "Outputs:",
    "cli.summary.plan": "Project plan: {summary}",
    "cli.relational.integrity_failed": "Relational integrity was not met ({count} violations).",
    # --- CLI --help -------------------------------------------------------- #
    "cli.help.description": "AI Synthetic Data Studio - the headless end-to-end pipeline",
    "cli.help.domain": "Domain / task description of the dataset to generate",
    "cli.help.project": (
        "Describe the PROJECT instead of the data: the planner decides what data is "
        "needed, the target variable, the class balance, which leakage columns to "
        "drop, and the train/test split"
    ),
    "cli.help.check_auth": "Print the credential status of every provider and exit",
    "cli.help.model": "Provider-specific model name",
    "cli.help.locale": "Faker locale (e.g. tr_TR)",
    "cli.help.hf_seed": "Fetch reference data from HuggingFace",
    "cli.help.hf_dataset": "Use a specific HF dataset id",
    "cli.help.web_seed": "Collect real reference (seed) data from the web",
    "cli.help.web_query": "Web search query, or a direct URL",
    "cli.help.formats": "Comma separated: csv,parquet,json",
    "cli.help.provenance": "Add legal provenance disclaimer header to CSV/Parquet outputs",
    "cli.help.export_pdf": "Generate executive PDF Data Quality & Privacy Audit Report (Pro)",
    "cli.help.push_to_hub": "Upload the clean data to this HF repo_id",
    "cli.help.public": "Create the HF repo as public",
    "cli.help.contamination": "IsolationForest anomaly rate (0 = off, the default). E.g. 0.05",
    "cli.help.no_correlation_guard": (
        "Turn off the rollback that protects target correlations from outlier cleaning"
    ),
    "cli.help.preserve_col": (
        "Anomaly column exempted from the Z-score and IsolationForest filters (e.g. is_fraud)"
    ),
    "cli.help.preserve_val": "Anomaly protection value (default: 1 or True)",
    "cli.help.inject_fraud": "Inject parametric fraud scenarios into the synthetic data",
    "cli.help.fraud_rate": "Fraud injection rate (default: 0.005, i.e. 0.5%)",
    "cli.help.fraud_target_col": "Fraud label column (default: is_fraud)",
    "cli.help.audit_privacy": (
        "Run heuristic privacy checks: nearest-neighbour memorisation test (DCR/NNDR), "
        "distribution divergence score and identifier column-name scan - not a compliance "
        "certification"
    ),
    "cli.help.fraud_table": "Which table the fraud injection applies to (default: the root table)",
    "cli.help.audit_table": (
        "Which table the privacy audit applies to: empty = the root table (default), "
        "'all' = every table, or a table name"
    ),
    "cli.help.ts_table": "Which table the time-series enrichment applies to (default: the root table)",
    "cli.help.expand_table": "Which table the feature expander applies to (default: the root table)",
    "cli.help.dirty_table": "Which table the dirty data injection applies to (default: the root table)",
    "cli.help.gemini_backend": (
        "Pick the Gemini backend for this run: 'aistudio' (API key, fast) or 'cli' "
        "(Antigravity session, slow). The stored setting is not changed"
    ),
    "cli.help.relational": "Generate a relational (multi-table) dataset: tables + foreign keys",
    "cli.help.max_tables": (
        "Upper table limit in relational mode (default 6; the contract's hard limit is 12)"
    ),
    "cli.help.no_repair_orphans": (
        "Do not delete orphan foreign keys, report them as an error (CI gate: exit "
        "code 3 when integrity is not met)"
    ),
    "cli.help.engine": (
        "Generation engine: 'llm' writes code and runs it in the sandbox (default), "
        "'parametric' compiles the schema directly (no LLM code; single- and "
        "multi-table), 'auto' falls back to 'parametric' when code generation runs out of "
        "attempts"
    ),
    "cli.help.time_series": (
        "Add time-series and velocity dynamics: chronological ordering, circadian "
        "rhythm, seconds_since_last_tx, velocity bursts"
    ),
    "cli.help.ts_timestamp_col": "Time-series timestamp column (default: transaction_timestamp)",
    "cli.help.ts_entity_col": (
        "Time-series entity id column; generated when missing (default: customer_id)"
    ),
    "cli.help.ts_start": "Time-series start (YYYY-MM-DD HH:MM:SS)",
    "cli.help.ts_end": "Time-series end (YYYY-MM-DD HH:MM:SS)",
    "cli.help.expand_features": (
        "Deterministic feature expansion: financial ratios, credit rating, time "
        "derivations and behavioural flags"
    ),
    "cli.help.dirty_rate": (
        "Controlled corruption rate (0-1, 0 = off). Applied AFTER validation; the "
        "is_corrupted / corruption_details columns are added"
    ),
    "cli.help.hardware": (
        "Print the hardware profile (CPU/RAM/GPU) and the recommended local model, then exit"
    ),
    # --- Validator ---------------------------------------------------------- #
    "validation.stage.duplicates": "Duplicate removal",
    "validation.stage.bounds": "Schema bounds",
    "validation.stage.rules": "Business rules",
    "validation.stage.z_score": "Z-score outliers",
    "validation.started": "Validation started ({rows} rows)",
    "validation.finished": "Validation finished: {rows_in} -> {rows_out} rows ({retention}% kept)",
    "validation.cancelled": "Validation was cancelled by the user",
    "validation.top_dropped_columns": "Columns dropping the most rows: {columns}",
    "validation.rule_violation": "Rule violation: '{rule}' -> {rows} rows removed ({pct}%)",
    "validation.rule_suspicious": "WARNING: '{rule}' alone removed {pct}% of the rows - it probably contradicts the column ranges, or the generator never applied it. Check the rule in the schema.",
    "validation.rule_skipped_every_row": "WARNING: no row satisfies '{rule}' - applying it would empty the dataset, so it was skipped. It contradicts the column types or ranges; check the rule in the schema.",
    "validation.z_skipped": "Z-score skipped (tail protection): {columns}",
    "validation.z_outliers": "Z-score outliers: {columns}",
    "validation.z_preserved": (
        "Z-score anomaly protection: column '{column}' saved {rows} extreme rows from deletion"
    ),
    "validation.iso_preserved": (
        "IsolationForest anomaly protection: column '{column}' saved {rows} extreme rows"
    ),
    "validation.preserved_summary": "Anomaly protection summary: {rows} rows kept by the '{column}' label",
    "validation.correlation_regressed": (
        "WARNING: correlation '{left} ~ {right}' dropped because of cleaning: "
        "r={before} -> {after} (threshold {threshold})"
    ),
    "validation.correlation_guard_reverted": (
        "Correlation guard engaged: outlier cleaning is being rolled back ({rows} rows "
        "came back). Disable it with --no-correlation-guard."
    ),
    "validation.correlation_line": (
        "Correlation [{pair}]: r={r} (expected: {sign}, min: {min_r}) [{verdict}]"
    ),
    "validation.correlations_unmet": "WARNING: {count} correlations missed the expectation: {pairs}",
    "validation.ks_summary": "KS distribution test: {passed}/{total} numeric columns match the reference",
    "validation.monotonicity_summary": "Monotonicity check: {passed}/{total} rules verified",
    "validation.monotonicity_line": (
        "[{x} -> {y} ({direction})]: Spearman r={r}, bin compliance={compliance}% [{verdict}]"
    ),
    "validation.privacy_nndr": "Privacy & NNDR: DCR={dcr}, NNDR={nndr} (memorisation risk: {risk})",
    "validation.hipaa_warning": "Identifier column-name scan: {summary}",
    "validation.hipaa_ok": (
        "Identifier column-name scan: no matches (column names only; values are not "
        "inspected)"
    ),
    "validation.verdict.ok": "OK",
    "validation.verdict.below": "BELOW EXPECTATION",
    "validation.verdict.violation": "VIOLATION",
    # --- Code generation (console only; LLM feedback stays untranslated) ---- #
    "codegen.starting": "Starting code generation (LLM)...",
    "codegen.written": "The LLM wrote the Python code ({lines} lines). Starting the sandbox test...",
    "codegen.written_relational": (
        "The LLM wrote Python code for {tables} tables ({lines} lines). Starting the "
        "sandbox test..."
    ),
    "codegen.attempt": "Attempt {attempt}/{total}: running the code in the sandbox...",
    "codegen.attempt_failed": "Attempt {attempt} failed: {error}",
    "codegen.hint": "Fix hint: {hint}",
    "codegen.auto_import": "Missing import added automatically ({line}), running again without an LLM call...",
    "codegen.return_wrapped": "A `return` was found outside any function; the code was wrapped in {name}(n_rows, seed) so it can run...",
    "codegen.return_rebound": "{count} `return` statement(s) outside any function were rebound to {name}; the entry point the code already defines is used...",
    "codegen.attempt_ok": "Attempt {attempt} succeeded: {rows} rows ({seconds} s, {columns} columns)",
    "codegen.attempt_ok_relational": (
        "Attempt {attempt} succeeded: {tables} tables ({seconds} s) - {counts}"
    ),
    "codegen.schema_mismatch": "Attempt {attempt}: {count} schema mismatches found",
    "codegen.mismatch_item": "Mismatch: {issue}",
    "codegen.mismatch_more": "... and {count} more mismatches",
    "codegen.repeated_error": "The same error repeated - asking the LLM to change its approach...",
    "codegen.feeding_back": "Feeding the error back to the LLM, fixing the code...",
    "codegen.gave_up": "No working code after {attempts} attempts. Last error:\n{error}",
    "codegen.fix_call_failed": "The code-fix call failed: {error}",
    "codegen.unexpected_state": "Unexpected state",
    "codegen.cancelled": "Cancelled by the user",
    # --- Relational validator ---------------------------------------------- #
    "relational.orphans_removed": "Orphan cleanup [{relationship}]: {rows} rows removed",
    "relational.pk_not_unique": (
        "WARNING: primary key '{pk}' of '{table}' is not unique ({duplicates} "
        "duplicates, {nulls} nulls)"
    ),
    "relational.fk_line": "Foreign key [{relationship}]: {orphans} orphan rows ({pct}%) [{verdict}]",
    "relational.verdict.orphans": "ORPHANS FOUND",
    "relational.cardinality_line": (
        "Cardinality [{relationship}]: mean {observed} per parent (expected {expected}) [{verdict}]"
    ),

    # --- Monotonicity validator --------------------------------------------- #
    "monotonicity.no_rules": "No monotonicity rule is defined.",
    "monotonicity.report_title": "Monotonicity & Credit Risk Scorecard Compliance Report",
    "monotonicity.table_header": (
        "| Variable X | Target/Dependent Y | Direction | Spearman $r_s$ | Bin compliance "
        "| Pair compliance | Status |"
    ),
    "monotonicity.compliant": "Compliant",
    "monotonicity.below_threshold": (
        "Bin monotonicity compliance ({binned}%) or pairwise compliance ({pairwise}%) "
        "is below the threshold ({threshold}%)"
    ),
    "monotonicity.column_missing": "The column is missing from the dataframe, or the data is empty",
    "monotonicity.not_enough_rows": "Not enough valid numeric rows (<10)",
    # --- HIPAA identifier catalogue ---------------------------------------- #
    "hipaa.title.names": "Names",
    "hipaa.title.geographic": "Geographic subdivisions smaller than a state",
    "hipaa.title.dates": "Dates directly related to an individual",
    "hipaa.title.phone": "Telephone numbers",
    "hipaa.title.fax": "Fax numbers",
    "hipaa.title.ssn": "Social security / national id numbers",
    "hipaa.title.mrn": "Medical record numbers",
    "hipaa.title.health_plan": "Health plan beneficiary numbers",
    "hipaa.title.account": "Account numbers",
    "hipaa.title.vehicle": "Vehicle identifiers and licence plates (VIN)",
    "hipaa.title.device": "Device identifiers and serial numbers",
    "hipaa.title.biometric": "Biometric identifiers",
    "hipaa.title.face": "Full-face photos and comparable images",
    "hipaa.title.unique_code": "Any other unique identifying number or code",
    "hipaa.title.email": "Email addresses",
    "hipaa.title.certificate": "Certificate / licence numbers",
    "hipaa.title.url": "Web URLs",
    "hipaa.title.ip": "IP addresses",
    "hipaa.category.direct": "Direct identifier",
    "hipaa.category.quasi": "Quasi-identifier",
    "hipaa.category.timestamp": "Timestamp (date shifting required)",
    "hipaa.category.health_system": "Health system identifier",
    "hipaa.category.health_financial": "Health financial identifier",
    "hipaa.category.financial": "Financial identifier",
    "hipaa.category.asset": "Asset identifier",
    "hipaa.category.hardware": "Hardware identifier",
    "hipaa.category.digital": "Digital trace",
    "hipaa.category.network": "Network identifier",
    "hipaa.category.visual_biometric": "Visual biometric",
    "hipaa.category.government_id": "Government-issued identifier",
    "hipaa.category.official_document": "Official document",
    "hipaa.category.biometric": "Biometric data",

    # --- Privacy audit report ----------------------------------------------- #
    "privacy.report.title": "Privacy Check Report (heuristic)",
    "privacy.report.scope": (
        "**Scope:** heuristic checks only - a nearest-neighbour memorisation test against "
        "reference data (DCR/NNDR), a histogram divergence score, and a column-name scan "
        "that uses the 18 HIPAA Safe Harbor identifier categories as a checklist. It is "
        "not a differential-privacy guarantee and not a HIPAA compliance certification."
    ),
    "privacy.report.table": "Table",
    "privacy.report.summary_heading": "Summary",
    "privacy.report.overall_status": "Overall status",
    "privacy.report.guarantee": "Memorisation check",
    "privacy.report.divergence": "Distribution divergence",
    "privacy.report.divergence_note": (
        "mean Jensen-Shannon distance between the synthetic and reference histograms of "
        "the shared numeric columns (20 bins at reference quantiles); 0 means identical "
        "histograms, 1 means no overlap. Small samples give values above 0 even for "
        "identical distributions. It is not a privacy measure."
    ),
    "privacy.report.memorisation_heading": "Reference Data Memorisation Analysis",
    "privacy.report.no_reference": (
        "No reference (seed) data was supplied, so the DCR/NNDR comparison did not run "
        "and the **memorisation risk was not measured**."
    ),
    "privacy.report.no_reference_table": (
        "There is no reference (seed) data for this table; the DCR/NNDR comparison "
        "could not run, so the **memorisation risk was not measured**."
    ),
    "privacy.report.nn_intro": (
        "A nearest-neighbour analysis checks whether synthetic rows sit closer to "
        "reference records than reference records sit to each other. Both are measured on "
        "the numeric columns the datasets share, standardised, on a random sample of "
        "rows; the baseline column is what uncopied data from the same distribution looks "
        "like:"
    ),
    "privacy.report.metric_header": (
        "| Metric | Synthetic → reference | Reference → reference (baseline) | Risk level "
        "|"
    ),
    "privacy.report.dcr_p5": "5th percentile DCR",
    "privacy.report.identical_matches": "Identical record count",
    "privacy.report.mean_nndr": "Mean NNDR",
    "privacy.report.low_nndr_share": "Share of rows with NNDR < 0.2",
    "privacy.report.nndr_note_label": "Reading NNDR:",
    "privacy.report.nndr_note": (
        "compare each value with its baseline, not with a fixed threshold. With one or "
        "two numeric columns a sizeable share of low ratios is normal. Identical rows or "
        "low ratios well above the baseline point to copied or near-copied records. A "
        "5th-percentile DCR below the baseline alone can also mean the synthetic data is "
        "concentrated in dense regions, so it raises the risk to MEDIUM at most."
    ),
    "privacy.report.hipaa_heading": "Identifier Column-Name Scan",
    "privacy.report.hipaa_scope": (
        "Column **names** are matched against patterns for the 18 HIPAA Safe Harbor "
        "identifier categories, and an age column is checked for values over 89. Cell "
        "values are not inspected: an identifier stored under an unrelated name is "
        "missed, and a harmless column whose name contains a pattern (such as "
        "`mobile_sessions`) is flagged."
    ),
    "privacy.report.audit_result": "Scan result",
    "privacy.report.all_passed": "NO MATCHES",
    "privacy.report.review_required": "COLUMNS TO REVIEW",
    "privacy.report.age_over_89": "Rows with age over 89",
    "privacy.report.age_rule": "HIPAA rule: ages over 89 must be grouped as 90+",
    "privacy.report.identifiers_heading": "Column Names Matching an Identifier Pattern",
    "privacy.report.identifiers_header": "| Column | Identifier category | Suggested action |",
    "privacy.report.no_identifiers": (
        "No column name matched an identifier pattern. Cell values were not inspected."
    ),
    "privacy.report.footer": (
        "Generated automatically by the AI Synthetic Data Studio PrivacyAuditor. These "
        "are heuristic checks; review the data yourself before sharing it."
    ),
    "privacy.action.mask": "Review; mask it or replace it with synthetic values (e.g. Faker).",
    "privacy.summary.compliant": "No identifier-like column names and no ages over 89 found.",
    "privacy.summary.findings": (
        "Found {columns} identifier-like column name(s) and {ages} row(s) with age over "
        "89."
    ),
    "privacy.assessment.copies_found": (
        "Possible copies of reference records (identical rows or low NNDR)"
    ),
    "privacy.assessment.no_copies": "No near-copies of reference records found in the sample",
    "privacy.assessment.not_measured": "Not measured - no reference data to compare against",
    # --- Schema contract validation ----------------------------------------- #
    "schema.error.empty_response": "The LLM response was empty - no JSON block found",
    "schema.error.no_json": "No valid JSON block was found in the LLM response",
    "schema.error.must_be_object": "{where} must be an object, got {got}",
    "schema.error.name_required": "{where}: 'name' is required and must be a non-empty string",
    "schema.error.bad_identifier": (
        "{where}: column name '{name}' is invalid - to be usable with df.eval it may "
        "only contain letters, digits and underscores, and must not start with a digit"
    ),
    "schema.error.bad_type": "{where} ('{name}'): 'type' must be one of: {valid}",
    "schema.error.bad_distribution": (
        "{where} ('{name}'): unknown distribution '{distribution}' - valid: {valid}"
    ),
    "schema.error.min_gt_max": "{where} ('{name}'): min ({low}) cannot be greater than max ({high})",
    "schema.error.target_ratio_range": "{where} ('{name}'): target_ratio must be within 0..1, got {value}",
    "schema.error.zero_prob_range": "{where} ('{name}'): zero_prob must be within 0..1, got {value}",
    "schema.error.p_index_range": "{where} ('{name}'): tweedie p_index must be strictly between 1 and 2, e.g. 1.5 (compound Poisson-gamma), got {value}",
    "schema.error.std_negative": "{where} ('{name}'): std cannot be negative",
    "schema.error.shape_positive": "{where} ('{name}'): shape must be positive",
    "schema.error.scale_positive": "{where} ('{name}'): scale must be positive",
    "schema.error.categories_required": (
        "{where} ('{name}'): a 'categories' list is required when type is 'category'"
    ),
    "schema.error.mean_required": "{where} ('{name}'): 'mean' is required when distribution is 'normal'",
    "schema.error.contract_object": "The Schema Contract must be a JSON object, got {got}",
    "schema.error.domain_required": "'domain' must be a non-empty string",
    "schema.error.columns_required": "'columns' must be a list with at least one column",
    "schema.error.duplicate_columns": "Duplicate column names: {columns}",
    "schema.error.row_count_positive": "'row_count_target' must be positive",
    "schema.error.row_count_int": "'row_count_target' must be an integer, got {value}",
    "schema.error.seed_int": "'random_seed' must be an integer",
    "schema.error.rules_list": "'business_rules' must be a list",
    "schema.error.correlations_list": "'correlations' must be a list",
    "schema.error.monotonicity_list": "'monotonicity_rules' must be a list",
    "schema.error.correlation_pair": "{where}: 'columns' must contain exactly 2 column names",
    "schema.error.expected_sign": "{where}: expected_sign must be 'positive' or 'negative', got '{sign}'",
    "schema.error.min_r_range": "{where}: min_r must be within -1..1",
    "schema.error.monotonicity_columns": (
        "{where}: 'column_x' and 'column_y' (or a 2-element 'columns') are required"
    ),
    "schema.error.direction": "{where}: direction must be 'increasing' or 'decreasing', got '{direction}'",
    "schema.error.min_compliance_range": "{where}: min_compliance_ratio must be within 0..1",
    "schema.error.primary_key_missing": "primary_key '{pk}' of table '{table}' is not among its columns",
    "schema.error.numeric_bool": "{where}: '{field}' must be numeric, got a boolean",
    "schema.error.numeric_expected": "{where}: '{field}' must be numeric, got {value}",
    "schema.warning.correlation_unknown_columns": (
        "Correlation rule dropped - unknown column(s) {columns} (defined: {known})"
    ),
    "schema.warning.correlation_not_numeric": (
        "Correlation rule dropped - {columns} is not numeric/bool, no correlation can be computed"
    ),
    "schema.warning.correlation_above_ceiling": "Correlation {columns}: min_r {requested} is above the most a bool column with this True ratio can reach ({ceiling}) - lowered to {lowered}",
    "schema.warning.monotonicity_unknown_columns": (
        "Monotonicity rule dropped - unknown column(s) [{x}, {y}] (defined: {known})"
    ),
    "schema.warning.monotonicity_not_numeric": (
        "Monotonicity rule dropped - [{x}, {y}] is not numeric/bool"
    ),
    "schema.warning.rule_unknown_names": "Business rule '{rule}' refers to undefined name(s) {names} - rule dropped",
    "schema.warning.rule_unparseable": "Business rule '{rule}' is not a valid row-wise expression - rule dropped",
    "schema.warning.rule_type_mismatch": "Business rule '{rule}' compares numeric/bool column(s) {columns} with text, which never matches - rule dropped",
    "schema.warning.rule_pins_bool": "Business rule '{rule}' forces bool column(s) {columns} to a single value, which would delete one whole class - that condition was removed from the rule",
    "schema.warning.bool_mean_as_ratio": "Column '{column}': a bool column's mean is its share of True values - used as target_ratio={ratio}",
    "schema.warning.p_index_boundary_dropped": "Column '{column}': tweedie p_index {value} sits on the boundary (it must lie strictly between 1 and 2) - dropped, the default is used",
    "schema.warning.preserve_column_missing": (
        "preserve_anomaly_column '{column}' was not found among the defined columns: {known}"
    ),
    # --- Dataset contract ---------------------------------------------------- #
    "contract.error.contract_object": "The Dataset Contract must be a JSON object, got {got}",
    "contract.error.field_required": "{where}: '{field}' is required and must be a non-empty string",
    "contract.error.tables_required": "'tables' must be a list with at least one table",
    "contract.error.duplicate_tables": "Duplicate table names: {tables}",
    "contract.error.relationships_list": "'relationships' must be a list",
    "contract.error.mean_per_parent_number": "{where}: 'mean_per_parent' must be a number",
    "contract.error.mean_per_parent_positive": "{where}: 'mean_per_parent' must be positive",
    "contract.error.min_per_parent_int": "{where}: 'min_per_parent' must be an integer",
    "contract.error.max_per_parent_int": "{where}: 'max_per_parent' must be an integer",
    "contract.error.max_lt_min": (
        "{where}: 'max_per_parent' ({high}) cannot be smaller than 'min_per_parent' ({low})"
    ),
    "contract.error.relationship_table_missing": (
        "Relationship '{label}': the {side} table '{table}' is not defined"
    ),
    "contract.error.relationship_column_missing": (
        "Relationship '{label}': column '{column}' does not exist in table '{table}'"
    ),
    "contract.error.self_parent": "Relationship '{label}': a table cannot be its own parent",
    "contract.error.no_root_table": "No root table found - the relationships may contain a cycle",
    "contract.error.cycle": (
        "The relationships contain a cycle, the generation order cannot be derived: {tables}"
    ),

    # --- Project planner ----------------------------------------------------- #
    "plan.error.plan_object": "The project plan must be a JSON object, got {got}",
    "plan.error.leakage_list": "'excluded_leakage' must be a list",
    "plan.error.target_required": (
        "'target' is required for the '{task}' task - a dataset without a target "
        "variable is not ready for training"
    ),
    "plan.error.class_ratio_required": (
        "'positive_class_ratio' is required for the '{task}' task - a classification "
        "dataset without a stated class balance is not useful"
    ),
    "plan.error.class_ratio_range": "'positive_class_ratio' must be between 0 and 1, got {value}",
    "plan.error.split_column_missing": "split: column '{column}' does not exist in table '{table}'",
    "plan.error.split_not_datetime": (
        "split: a temporal split needs '{column}' to be a 'datetime' column, it is '{got}'"
    ),
    "plan.warning.unsupervised_target": (
        "The task is 'unsupervised' but a target variable was given ({target}) - ignored."
    ),
    "plan.warning.class_ratio_ignored": "A class balance is meaningless for the '{task}' task - ignored.",
    "plan.warning.class_ratio_extreme": (
        "The class balance is extreme ({ratio}): a target at this rate may not yield a "
        "meaningful number of examples in the generated row count."
    ),
    "plan.warning.no_leakage": (
        "No leakage column was dropped. Most real problems have at least one field that "
        "is only known after the target event; the plan may have missed it."
    ),
    # --- Service layer errors ----------------------------------------------- #
    "service.error.package_missing": "The `{package}` package is not installed",
    "service.error.auth_failed": (
        "Authentication failed ({source}). The key is invalid or has expired."
    ),
    "service.error.forbidden": "The key is not allowed to perform this operation ({error}).",
    "service.error.unreachable": "The service could not be reached: {error}",
    "service.error.model_not_found": "Model not found: {model} ({error})",
    "service.error.anthropic_connection": "Anthropic connection error: {error}",
    "service.error.anthropic_rate_limit": "Anthropic kept answering 429 (rate limit) after 5 attempts. Wait a minute and run again, or pick a smaller model.",
    "service.error.anthropic_rate_limit_oauth": "Anthropic kept answering 429 (rate limit) after 5 attempts. The app is using your Claude Code subscription session, which shares its quota with every open Claude Code window - close those or wait a few minutes, or set an ANTHROPIC_API_KEY.",
    "service.error.anthropic_bad_key": "The Anthropic API key is invalid: {error}",
    "service.error.anthropic_server": "Anthropic server error {status}",
    "service.error.anthropic_api": "Anthropic API error {status}: {error}",
    "service.error.anthropic_empty": "Anthropic returned an empty response (stop_reason={reason})",
    "service.error.gemini_request": "Gemini request error: {error}",
    "service.error.gemini_server": "Gemini server error: {error}",
    "service.error.gemini_api": "Gemini API error: {error}",
    "service.error.gemini_empty": "Gemini returned an empty response",
    "service.error.ollama_unreachable": (
        "Could not connect to the Ollama daemon ({host}). Is `ollama serve` running?"
    ),
    "service.error.ollama_down": "The Ollama daemon is not running ({host}). Start it with: ollama serve",
    "service.error.ollama_model_missing": "Model not installed: {model}. Pull it with: ollama pull {model}",
    "service.error.ollama_bad_json_tags": "Ollama /api/tags returned invalid JSON",
    "service.error.ollama_bad_json": "Ollama returned invalid JSON",
    "service.error.ollama_pull_start": "The model download could not be started: {error}",
    "service.error.ollama_pull": "Ollama pull error: {error}",
    "service.error.ollama_timeout": "Ollama did not answer within {seconds} seconds - try a smaller model",
    "service.error.ollama_call_failed": "The Ollama call failed: {error}",
    "service.error.ollama_generic": "Ollama error: {error}",
    "service.error.ollama_empty": "Ollama returned an empty response",
    "service.error.ollama_thinking_exhausted": "{model} spent its whole output budget ({tokens} tokens) on reasoning and returned no answer. Reasoning models such as deepseek-r1 are slow for this task - a coder model such as qwen2.5-coder is recommended.",
    "service.ollama.thinking_retry": "{model} spent its output budget on reasoning; retrying once with {tokens} tokens",
    "service.ollama.empty_retry": "{model} returned an empty response; retrying once",
    "service.error.hf_temporary": "HF temporary error ({status}): {error}",
    "service.error.hf_auth": "HF authorisation error ({status}): {error}",
    "service.error.hf_connection": "HF connection error: {error}",
    "service.error.hf_generic": "HF error: {error}",
    "service.error.hf_dataset_empty": "The dataset is empty or could not be read: {dataset}",
    "service.error.hf_no_token": (
        "No HuggingFace token was found. Enter one in the Settings tab, or define the "
        "HF_TOKEN environment variable."
    ),
    "service.error.hf_empty_data": "There is no data to upload",
    "service.error.schema_retries": (
        "No valid Schema Contract after {attempts} attempts. Last error: {error}"
    ),
    "service.error.contract_retries": (
        "No valid Dataset Contract after {attempts} attempts. Last error: {error}"
    ),
    "service.error.plan_retries": (
        "No valid project plan after {attempts} attempts. Last error: {error}"
    ),
    "run.error.health_check": "The {provider} service could not be verified (model: {model}). {detail}",
    "run.error.health_hint": "Check the API key / the daemon.",

    # --- Antigravity CLI (agy) ----------------------------------------------- #
    "service.agy.not_found": "`agy` command not found. Antigravity CLI is not installed: {url}",
    "service.agy.not_installed": "`agy` command not found - Antigravity CLI is not installed",
    "service.agy.session_unverified": (
        "Antigravity CLI is installed but session could not be verified. "
        "Run `agy` in a terminal and sign in."
    ),
    "service.agy.session_ok": "Antigravity CLI session active - {count} models available",
    "service.agy.model_invalid": (
        "Model '{model}' is not recognized in Antigravity CLI. Open the Model list in the "
        "Pipeline tab and select a valid one{hint}"
    ),
    "service.agy.model_hint": " (e.g. {model})",
    "service.agy.no_details": "no details",
    "service.agy.not_found_hint": (
        "Antigravity CLI (`agy`) not found. Installation: {url} - or provide an "
        "AI Studio API key for Gemini."
    ),
    "service.agy.credential_label": "Antigravity CLI (agy) session",
    "service.agy.model_missing": "Model '{model}' is not available in Antigravity CLI. Available models: {models}",
    "service.agy.prompt_too_long": (
        "Prompt is too long for Antigravity CLI ({length} chars, limit {limit}). "
        "Reduce the row count or switch to an AI Studio API key."
    ),
    "service.agy.empty_attempts": (
        "Antigravity CLI returned an empty response after {attempts} attempts. The agent CLI "
        "may have called a tool instead of returning text; switching to an AI Studio API key "
        "eliminates this behavior. Raw output: {output}"
    ),
    "service.agy.call_started": (
        "agy call started - CLI startup alone takes ~200 s, the first step event comes after that."
    ),
    "service.agy.timeout": (
        "Antigravity CLI did not respond within {seconds} seconds. The agent CLI is slow; "
        "try a smaller model (e.g. gemini-3.8-flash-low) or switch to an AI Studio API key."
    ),
    "service.agy.exec_failed": "Antigravity CLI could not be executed: {error}",
    "service.agy.cli_error": "Antigravity CLI returned an error: {error}",
    "service.agy.status_error": "Antigravity CLI returned '{status}' status: {error}",
    "service.agy.still_running": "agy still running ({seconds} s)",
    "service.agy.step_progress": "agy step: {type} ({state}){duration}",
    "service.agy.step_duration": " - {seconds} s",
    "service.agy.no_result_event": "Antigravity CLI returned no result event: {output}",

    # --- Validator short rationales ------------------------------------------ #
    "validation.z_skip.heavy_tail": "distribution '{dist}' is heavy-tailed / count type",
    "validation.z_skip.zero_inflated": "zero ratio {pct}% (zero-inflated)",
    "validation.z_skip.iqr_zero": "half of the values are concentrated at a single point (IQR=0)",
    "validation.z_skip.bowley_skew": "Bowley skewness {skew} (non-symmetric)",
    "validation.iso_skip.few_rows": "insufficient complete rows",
    "validation.corr_skip.not_numeric": "column is not numeric or missing",
    "validation.corr_skip.constant": "correlation cannot be computed (constant column?)",
    "validation.dist_skip.no_seed": "no reference seed data",
    "validation.dist_skip.no_scipy": "scipy is not installed",
    "validation.dist_skip.no_common_numeric": "no common numeric columns found",
    "validation.stage.correlation_guard": "Correlation guard (revert)",

    # --- Relational validator reasons --------------------------------------- #
    "relational.reason.no_table_or_column": "missing table or column",
    "relational.reason.no_table": "missing table",
    "relational.reason.no_key_column": "missing key column",

    # --- Dataset & schema contract errors ------------------------------------ #
    "contract.error.min_per_parent_negative": "{where}: 'min_per_parent' cannot be negative",
    "schema.error.foreign_keys_missing": "foreign_keys in table '{table}' not found in columns: {keys}",

    # --- Cloud & Ollama scattered errors ------------------------------------ #
    "service.error.gemini_bad_key": (
        "Gemini API key is invalid or unauthorized. Verify at https://aistudio.google.com/apikey "
        "- or choose Antigravity CLI login for keyless access."
    ),
    "service.error.gemini_quota": (
        "Gemini rate limit exceeded. Please wait a moment and retry, or select a smaller model."
    ),
    "service.error.gemini_model_missing": "Model '{model}' not found. Select another model from the model list.",
    "service.error.gemini_rejected": "Request rejected: {error}",
    "service.error.unknown_provider": "Unknown provider: {provider}",
    "service.error.ollama_delete": "Could not delete model: {error}",
    "console.title": "Console",
    "console.clear": "Clear",
    "settings.cost.summary": "Total {calls} calls | {input_tokens} input + {output_tokens} output tokens | est. ${cost}",
    "pipeline.engine.multi_agent": "🤖 Multi-Agent Council",
    # --- sonradan eklenenler: dogrulama, kimlik, ayarlar, donanim, planlayici --- #
    "common.percent": "{value}%",
    "common.unknown_error": "unknown error",
    "schema.summary": "{domain} | {columns} columns | target {rows} rows | seed {seed} | {rules} rules | {correlations} correlations",
    "schema.summary.monotonicity": " | {count} monotonicity rules",
    "schema.summary.anomaly": " | anomaly protection: {column}",
    "schema.error.missing_fields": "Schema Contract is missing required field(s): {fields}",
    "schema.error.root_table_missing": "root_table '{root}' is not one of the tables: {tables}",
    "contract.error.too_many_tables": "'tables' may hold at most {limit} tables, got {count}",
    "schema.warning.distribution_dropped": "Column '{column}': unsupported distribution '{distribution}' was dropped - values stay within min/max",
    "schema.warning.datetime_bounds_moved": "Column '{column}': datetime bounds were not numbers; the range ({range}) was moved into the description",
    "schema.warning.normal_mean_filled": "Column '{column}': the 'normal' distribution had no mean; using the midpoint of min/max ({mean})",
    "validation.correlation_skipped": "Correlation [{pair}]: not measured - {reason}",
    "result.correlation_expected": "expected {sign} >= {min_r}",
    "relational.violation.mean": "mean {observed}, expected {expected} (+/-{tolerance}%)",
    "relational.violation.max": "maximum {observed}, upper limit {limit}",
    "run.warning_prefix": "WARNING: {message}",
    "run.agents.gathering": "🤖 Convening the Multi-Agent Council (Domain, Statistician, Critic, Engineer)...",
    "run.agents.started": "[Agent Council] Deliberation and review started (up to {rounds} rounds)...",
    "run.agents.consensus": "[Agent Council] Consensus reached: {tables} table(s) compiled.",
    "cli.help.agentic": "Design the schema together with the Multi-Agent Council (Domain, Statistician, Critic, Engineer).",
    "cli.help.max_agent_rounds": "Number of critique and deliberation rounds between the agents (default: 2).",
    "cli.auth.none_hint": "Enter a key in the Settings tab, or:",
    "auth.source.unknown_provider": "unknown provider",
    "auth.source.keyring": "OS keyring (credential store)",
    "auth.source.env_var": "{var} environment variable",
    "auth.source.claude_code": "Claude Code OAuth session",
    "auth.source.not_found": "not found in any source",
    "auth.source.ant_profile": "`ant auth login` profile",
    "auth.source.agy_session": "Antigravity CLI (agy) session",
    "auth.source.hf_login": "huggingface-cli login token",
    "auth.source.direct": "passed directly",
    "auth.oauth.claude_note": "Copy the token from the console that opens and paste it into the 'API key' field above - the session then no longer expires.",
    "auth.oauth.claude_expired": "Claude Code session found but it has EXPIRED - run `claude` in a terminal to renew it",
    "auth.oauth.claude_active": "Signed in with Claude Code OAuth",
    "auth.oauth.hours_left": " (valid for about {hours} hours)",
    "auth.oauth.claude_expiring_note": "This session expires in {hours} hours. For permanent use, create a long-lived token with 'Sign in' or enter an API key.",
    "auth.oauth.profile": "Profile: {path}",
    "auth.oauth.agy_installed": "Antigravity CLI is installed - verify the session with 'Test'",
    "auth.oauth.agy_missing": "Antigravity CLI (`agy`) is not installed",
    "auth.oauth.agy_note": "Uses your existing Antigravity session - no API key, GCP project or billing needed. The trade-off is speed: the agent CLI loads its own context on every call, so a single step can take minutes.",
    "auth.oauth.hf_token_saved": "Token saved",
    "auth.oauth.hf_not_logged_in": "huggingface-cli login has not been run",
    "auth.missing.message": "No credentials found for {provider}. Enter a key in the Settings tab or set the {env_vars} environment variable{extra}.",
    "auth.missing.extra_anthropic": ", or sign in with the `claude` CLI",
    "auth.missing.extra_gemini": " (free at https://aistudio.google.com), or choose the Antigravity CLI sign-in",
    "auth.missing.extra_huggingface": ", or run `huggingface-cli login`",
    "settings.hf.signed_in": "Signed in: {name}",
    "settings.hf.token_invalid": "Token could not be verified: {error}",
    "settings.oauth.unsupported": "This provider has no OAuth sign-in",
    "settings.oauth.command_not_found": "{command} not found",
    "settings.oauth.launch_failed": "Could not start: {error}",
    "settings.ollama.daemon_down": "The Ollama daemon is not running - start it with: ollama serve",
    "settings.ollama.no_models": "Ollama {version} is running - no models installed",
    "settings.ollama.check_failed": "Could not check: {error}",
    "settings.ollama.enter_model_name": "Enter a model name first",
    "settings.ollama.pull_starting": "Starting download...",
    "settings.ollama.pull_done": "Downloaded: {model}",
    "settings.ollama.pull_failed": "Download failed: {model}",
    "settings.ollama.pull_error": "Error: {error}",
    "service.error.refused": "The model refused the request{detail}",
    "hardware.cores": "{physical} physical / {logical} logical",
    "hardware.cpu_unknown": "Unknown CPU",
    "hardware.gpu_none": "None / integrated graphics",
    "hardware.notes.enterprise": "High-end GPU ({gpu}, {vram} GB VRAM). 14B and 32B models can run at full CUDA speed.",
    "hardware.notes.high": "Strong GPU ({gpu}, {vram} GB VRAM). A 7B model runs entirely on the graphics card without lag.",
    "hardware.notes.mid": "Mid-range system ({vram} GB VRAM / {ram} GB RAM). A 7B Q4 or 3B model is recommended.",
    "hardware.notes.low": "Low-end hardware / integrated graphics. Run the 986 MB Qwen 1.5B model in CPU mode.",
    "hardware.report.title": "HARDWARE PROFILE AND MODEL RECOMMENDATION",
    "hardware.report.cpu": "CPU:",
    "hardware.report.cores": "Cores:",
    "hardware.report.ram": "System RAM:",
    "hardware.report.ram_value": "{total} GB (available: {available} GB)",
    "hardware.report.gpu": "Graphics card:",
    "hardware.report.gpu_value": "{gpu} ({vram} GB VRAM)",
    "hardware.report.tier": "Hardware tier:",
    "hardware.report.mode": "Execution mode:",
    "hardware.report.model": "Recommended model:",
    "hardware.report.rows": "Recommended rows:",
    "hardware.report.rows_value": "optimised for up to {rows} rows",
    "hardware.report.notes": "Notes:",
    "ollama.model.balanced": "Balanced for code generation - recommended",
    "ollama.model.better_code": "Better code, needs more RAM",
    "ollama.model.best_code": "Best code quality, 32 GB+ RAM",
    "ollama.model.strong_code": "Strong code model",
    "ollama.model.general": "General purpose",
    "ollama.model.general_fast": "General purpose, fast",
    "ollama.model.light_fast": "Lightweight, fast",
    "ollama.model.reasoning": "Strong reasoning",
    "app.crash.title": "AI Synthetic Data Studio - Unexpected error",
    "app.crash.body": "The application could not start.\n\n{error}\n\nDetails: {path}",
    "plan.error.split_kind": "{where}: 'kind' must be one of: {valid}",
    "plan.error.dataset_required": "'dataset' is required (the Dataset Contract)",
    "plan.error.task_type": "'task_type' must be one of: {valid}",
    "plan.error.leakage_required": "'excluded_leakage' is required - show which columns would leak the target (give an empty list if none would)",
    "plan.error.class_ratio_number": "'positive_class_ratio' must be a number, got {value}",
    "plan.error.target_column_missing": "Target column '{column}' does not exist in table '{table}'. Defined columns: {columns}",
    "plan.error.leakage_still_present": "Column(s) declared as leakage are still in the contract: {columns}. Excluded columns must not be generated - remove them from the contract or from the leakage list.",
    "plan.error.target_is_leakage": "Target column '{column}' is also marked as leakage",
    "plan.error.table_missing": "{where}: table '{table}' is not in the contract. Defined tables: {tables}",
    "plan.error.split_column_required": "split: a '{kind}' split needs a 'column'",
    "plan.error.ratio_disagreement": "The plan states a class balance of {plan_ratio} but '{target}' has target_ratio {column_ratio}. Both must state the same number.",
    "plan.warning.no_split": "No train/test split given - a default random split may be wrong (for time-dependent data or several rows per entity).",
    "plan.summary.task": "task: {task}",
    "plan.summary.target": "target: {target}",
    "plan.summary.positive_class": "positive class: {ratio}",
    "plan.summary.tables": "{count} tables",
    "plan.summary.leakage": "{count} leakage columns removed",
    "plan.summary.split": "split: {kind}",
    "web.more_sources": "(+{count} sources)",
    "hipaa.category.unique_key": "Unique key",

    # --- Schema Sanity Checker ------------------------------------------- #
    "sanity.report.clean": "Schema sanity check passed — no semantic issues detected.",
    "sanity.bounds.amount_missing_min": "'{column}' looks like a monetary amount but carries no lower bound; min was set to 0 so negative values cannot be generated.",
    "sanity.bounds.amount_negative_min": "'{column}' looks like a monetary amount but declared min={declared}; raised to 0. If negative values are intended, say so in the column name (net_, adjustment_, ...) or turn auto-correction off.",
    "sanity.correlation.ambiguous_pair": "{col_a} and {col_b} form a domain pair where a positive correlation can be correct; left unchanged - review it yourself.",
    "sanity.correlation.risk_asset_inverted": (
        "Suspected semantic inversion: '{col_a}' ({cat_a}) ↔ '{col_b}' ({cat_b}) "
        "should have a NEGATIVE correlation, but POSITIVE was specified."
    ),
    "sanity.correlation.positive_pair_inverted": (
        "Suspected semantic inversion: '{col_a}' ↔ '{col_b}' are a known positive pair, "
        "but NEGATIVE correlation was specified."
    ),
    "sanity.monotonicity.asset_risk_inverted": (
        "Suspected monotonicity inversion: '{col_x}' (asset) ↑ → '{col_y}' (risk) "
        "should be DECREASING, but INCREASING was specified."
    ),
    "sanity.monotonicity.risk_asset_inverted": (
        "Suspected monotonicity inversion: '{col_x}' (risk) ↑ → '{col_y}' (asset) "
        "should be DECREASING, but INCREASING was specified."
    ),
    "sanity.transitivity.violation": (
        "Correlation transitivity conflict: {col_a}~{col_b} ({sign_ab}), "
        "{col_b}~{col_c} ({sign_bc}) implies {col_a}~{col_c} should be "
        "{sign_ab}×{sign_bc}, but ({sign_ac}) was specified."
    ),
    # --- Licensing & Pro Edition ----------------------------------------- #
    "license.error.pro_required": "An active Pro or Enterprise license is required to use {feature}.",
    "license.status.missing": "No license installed (Community Edition)",
    "license.status.invalid_format": "Invalid license key format",
    "license.status.invalid_encoding": "Malformed license encoding",
    "license.status.signature_failed": "Invalid cryptographic signature",
    "license.status.invalid_payload": "Corrupted license data",
    "license.status.clock_tampered": "License clock check failed: the system clock is behind a previously recorded date. Correct the system time and restart.",
    "license.status.bad_expiry": "License expiry date could not be read",
    "license.status.not_persisted": "License verified but could not be saved; it will be lost on restart",
    "pipeline.warn.pdf_requires_license": "The audit PDF was not written: it needs an active Pro or Enterprise licence.",
    "pipeline.warn.pdf_failed": "The audit PDF could not be written: {error}",
    "license.status.revoked": "This licence key has been revoked ({license_key})",
    "verify.result.unsigned": "This file carries no provenance signature; it declares its origin but nothing vouches for it.",
    "verify.result.license": "Licence signature valid - issued to key {license_key} ({tier})",
    "verify.result.revoked": "The licence that signed this file has been revoked",
    "verify.result.signature": "Declaration signature valid - the declaration was produced by that licence",
    "verify.result.content": "Content digest matches - the file is the data the declaration describes",
    "verify.result.content_unchecked": "Content digest not checked (no data file given); declared {digest}...",
    "verify.error.unsigned": "No signature block found in the file.",
    "verify.error.license_signature": "The embedded licence was not issued by AI Synthetic Data Studio.",
    "verify.error.license_unreadable": "The embedded licence could not be read: {error}",
    "verify.error.revoked": "Licence {license_key} appears in the revocation list.",
    "verify.error.no_report_key": "The licence predates report signing and carries no report key.",
    "verify.error.report_signature": "The declaration was not signed by the licence it names.",
    "verify.error.report_unreadable": "The declaration signature could not be read: {error}",
    "verify.error.content_mismatch": "The data does not match the digest in the declaration; the file was changed after signing.",
    "verify.error.token_format": "Malformed licence token in the signature block.",
    "cli.help.verify_report": "verify a generated file's provenance signature offline (csv/json/parquet/pdf)",
    "cli.verify.missing_file": "file not found",
    "license.status.expired": "License expired on {date}",
    "license.status.valid": "Active and verified",
    "license.tier.community": "Community Edition",
    "license.tier.pro": "Pro Edition",
    "license.tier.enterprise": "Enterprise Edition",
    # --- GUI License & Edition Management -------------------------------- #
    "app.header.license_community": "Community",
    "app.header.license_pro": "PRO",
    "app.header.license_enterprise": "ENTERPRISE",
    "settings.license.title": "License & Edition",
    "settings.license.note": "AI Synthetic Data Studio is open-core. Activate Pro for Executive PDF Audit Reports and advanced compliance tools.",
    "settings.license.tier": "Current Edition: {tier}",
    "settings.license.activate": "Activate License...",
    "settings.license.deactivate": "Deactivate",
    "settings.license.deactivate_confirm": "Are you sure you want to remove the current license?",
    "settings.license.key_placeholder": "Paste your ADS-... license key here",
    "pipeline.button.export_pdf": "Audit Report (PDF)",
    "pipeline.export.pdf_checkbox": "Generate Executive PDF Audit Report (Pro)",
    "license.dialog.title": "License & Edition Activation",
    "license.dialog.heading": "Unlock Pro & Enterprise Features",
    "license.dialog.subheading": "Air-gapped offline validation • Executive PDF Reports • Compliance Certification",
    "license.dialog.enter_key": "Enter License Key",
    "license.dialog.activate_btn": "Activate License",
    "license.dialog.buy_btn": "Get a License Key",
    "license.dialog.success": "License successfully activated! Welcome to {tier}.",
    "license.dialog.activated_details": "Registered to: {email} • Tier: {tier} • Expiry: {expiry}",
}
