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
    "result.relational.pk_not_unique": "WARNING: primary key '{key}' of '{table}' is not unique",
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
    "pipeline.error.parametric_relational": (
        "The parametric engine does not support multi-table generation: it cannot "
        "maintain foreign-key consistency. Switch the engine to 'LLM code generation' "
        "or turn the relational switch off."
    ),
    "pipeline.error.folder_open": "The folder could not be opened: {error}",
}
