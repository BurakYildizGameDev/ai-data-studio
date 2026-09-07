"""Geçmiş ekranı - önceki çalıştırmalar, iş durumları ve raporları.

Mimari kuralı: Bu görünüm doğrudan veritabanı bağlantısı açmaz; tüm okuma işlemleri
StateManager örneği üzerinden gerçekleştirilir.
"""
from __future__ import annotations

from typing import Callable, List, Optional

import customtkinter as ctk
from ...i18n import t

STATUS_COLORS = {
    "done": "#81c784",
    "running": "#4fc3f7",
    "failed": "#e57373",
    "cancelled": "#ffb74d",
    "interrupted": "#ffb74d",
    "pending": "#8a8a8a",
}


class HistoryView(ctk.CTkFrame):
    def __init__(self, master, state_manager, on_resume: Optional[Callable[[int], None]] = None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state_manager
        self.on_resume = on_resume
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=t("history.title"),
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text=t("history.refresh"), width=70, command=self.refresh).grid(
            row=0, column=1, sticky="e", padx=(0, 6))
        ctk.CTkButton(header, text=t("history.clear"), width=70, fg_color="#b71c1c", hover_color="#c62828",
                      command=self._on_clear).grid(row=0, column=2, sticky="e")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=2, uniform="h")
        body.grid_columnconfigure(1, weight=3, uniform="h")
        body.grid_rowconfigure(0, weight=1)

        self.job_list = ctk.CTkScrollableFrame(body, label_text=t("history.jobs"))
        self.job_list.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.job_list.grid_columnconfigure(0, weight=1)

        detail = ctk.CTkFrame(body)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_rowconfigure(0, weight=1)
        self.detail_box = ctk.CTkTextbox(detail, wrap="word",
                                         font=ctk.CTkFont(family="Consolas", size=12))
        self.detail_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.detail_box.insert("1.0", t("history.pick_job"))
        self.detail_box.configure(state="disabled")

        self._buttons: List[ctk.CTkButton] = []
        self.refresh()

    # ------------------------------------------------------------------ #
    def _on_clear(self) -> None:
        self.state.clear_history()
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", t("history.cleared"))
        self.detail_box.configure(state="disabled")
        self.refresh()

    def refresh(self) -> None:
        for widget in self.job_list.winfo_children():
            widget.destroy()
        self._buttons.clear()

        jobs = self.state.list_jobs(limit=100)
        if not jobs:
            ctk.CTkLabel(self.job_list, text=t("history.empty"),
                         text_color="#8a8a8a").grid(row=0, column=0, pady=20)
            return

        for i, job in enumerate(jobs):
            color = STATUS_COLORS.get(job["status"], "#8a8a8a")
            text = "#%d  %s\n%s  |  %s" % (
                job["job_id"],
                (job["domain"] or job["prompt"] or "")[:34],
                job["status"],
                (job["created_at"] or "")[:16].replace("T", " "),
            )
            button = ctk.CTkButton(
                self.job_list, text=text, anchor="w", height=48, fg_color="#2b2b2b",
                hover_color="#3a3a3a", text_color=color,
                font=ctk.CTkFont(size=11),
                command=lambda jid=job["job_id"]: self.show_job(jid),
            )
            button.grid(row=i, column=0, sticky="ew", pady=2, padx=2)
            self._buttons.append(button)

    def show_job(self, job_id: int) -> None:
        job = self.state.get_job(job_id)
        if not job:
            return
        report = self.state.get_report(job_id)
        cost = self.state.get_cost_summary(job_id)

        def field(key, value):
            """Etiketi sabit genişlikte hizalar - çeviri uzunlukları farklıdır."""
            return "%-22s: %s" % (t(key), value)

        lines: List[str] = [
            "JOB #%d" % job_id,
            "=" * 60,
            field("history.field.status", job["status"]),
            field("history.field.domain", job["domain"] or "-"),
            field("history.field.prompt", job["prompt"] or "-"),
            field("history.field.provider",
                  "%s / %s" % (job["provider"] or "-", job["model"] or "-")),
            field("history.field.created", (job["created_at"] or "").replace("T", " ")),
            field("history.field.updated", (job["updated_at"] or "").replace("T", " ")),
            field("history.field.step",
                  "%s/%s - %s" % (job["current_step"], 7, job["step_name"] or "-")),
            field("history.field.seed", job["random_seed"]),
            field("history.field.rows_generated",
                  format(job["generated_rows_count"] or 0, ",")),
            field("history.field.rows_clean",
                  format(job["validated_rows_count"] or 0, ",")),
            field("history.field.cost", "$%.4f (%s)" % (
                cost.get("cost_usd", 0.0),
                t("history.field.calls", calls=cost.get("calls", 0)))),
        ]
        if job["output_path"]:
            lines.append(field("history.field.output", job["output_path"]))
        if job["error"]:
            lines += ["", t("history.section.error"), "-" * 60, str(job["error"])]

        schema = self.state.get_schema(job_id)
        if schema:
            lines += ["", t("history.section.schema"), "-" * 60,
                      t("history.schema.columns",
                        columns=", ".join(c["name"] for c in schema.get("columns", [])))]
            for rule in schema.get("business_rules", []):
                lines.append("  " + t("history.schema.rule", rule=rule))

        if report:
            lines += ["", t("history.section.validation"), "-" * 60,
                      "  " + t("history.validation.rows",
                               rows_in=format(report.get("rows_in", 0), ","),
                               rows_out=format(report.get("rows_out", 0), ","),
                               retention="%.1f" % report.get("retention_pct", 0.0))]
            for stage in report.get("stages", []):
                lines.append("  %-24s -%s" % (stage["stage"], format(stage["removed"], ",")))
            for corr in report.get("correlations", []):
                lines.append("  " + t(
                    "history.validation.correlation",
                    pair="/".join(corr["pair"]), r=corr.get("actual_r"),
                    verdict=t("history.verdict.pass") if corr.get("pass")
                    else t("history.verdict.fail")))

        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", "\n".join(lines))
        self.detail_box.configure(state="disabled")
