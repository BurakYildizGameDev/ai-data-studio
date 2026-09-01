"""Geçmiş ekranı - önceki çalıştırmalar, iş durumları ve raporları.

Mimari kuralı: Bu görünüm doğrudan veritabanı bağlantısı açmaz; tüm okuma işlemleri
StateManager örneği üzerinden gerçekleştirilir.
"""
from __future__ import annotations

from typing import Callable, List, Optional

import customtkinter as ctk

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
        ctk.CTkLabel(header, text="Geçmiş İşler",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="Yenile", width=70, command=self.refresh).grid(
            row=0, column=1, sticky="e", padx=(0, 6))
        ctk.CTkButton(header, text="Temizle", width=70, fg_color="#b71c1c", hover_color="#c62828",
                      command=self._on_clear).grid(row=0, column=2, sticky="e")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=2, uniform="h")
        body.grid_columnconfigure(1, weight=3, uniform="h")
        body.grid_rowconfigure(0, weight=1)

        self.job_list = ctk.CTkScrollableFrame(body, label_text="İşler")
        self.job_list.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.job_list.grid_columnconfigure(0, weight=1)

        detail = ctk.CTkFrame(body)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_rowconfigure(0, weight=1)
        self.detail_box = ctk.CTkTextbox(detail, wrap="word",
                                         font=ctk.CTkFont(family="Consolas", size=12))
        self.detail_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.detail_box.insert("1.0", "Soldan bir is seçin.")
        self.detail_box.configure(state="disabled")

        self._buttons: List[ctk.CTkButton] = []
        self.refresh()

    # ------------------------------------------------------------------ #
    def _on_clear(self) -> None:
        self.state.clear_history()
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", "Tüm geçmiş işler temizlendi.")
        self.detail_box.configure(state="disabled")
        self.refresh()

    def refresh(self) -> None:
        for widget in self.job_list.winfo_children():
            widget.destroy()
        self._buttons.clear()

        jobs = self.state.list_jobs(limit=100)
        if not jobs:
            ctk.CTkLabel(self.job_list, text="Henüz çalıştırılmış bir is yok.",
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

        lines: List[str] = [
            "JOB #%d" % job_id,
            "=" * 60,
            "Durum          : %s" % job["status"],
            "Domain         : %s" % (job["domain"] or "-"),
            "İstek          : %s" % (job["prompt"] or "-"),
            "Sağlayıcı      : %s / %s" % (job["provider"] or "-", job["model"] or "-"),
            "Oluşturuldu    : %s" % (job["created_at"] or "").replace("T", " "),
            "Güncellendi    : %s" % (job["updated_at"] or "").replace("T", " "),
            "Adım           : %s/%s - %s" % (job["current_step"], 7, job["step_name"] or "-"),
            "Random seed    : %s" % job["random_seed"],
            "Üretilen satır : %s" % format(job["generated_rows_count"] or 0, ","),
            "Temiz satır    : %s" % format(job["validated_rows_count"] or 0, ","),
            "LLM maliyeti   : $%.4f (%s çağrı)" % (cost.get("cost_usd", 0.0),
                                                   cost.get("calls", 0)),
        ]
        if job["output_path"]:
            lines.append("Çıktı          : %s" % job["output_path"])
        if job["error"]:
            lines += ["", "HATA", "-" * 60, str(job["error"])]

        schema = self.state.get_schema(job_id)
        if schema:
            lines += ["", "ŞEMA", "-" * 60,
                      "Kolonlar: " + ", ".join(c["name"] for c in schema.get("columns", []))]
            for rule in schema.get("business_rules", []):
                lines.append("  kural: %s" % rule)

        if report:
            lines += ["", "VALIDASYON", "-" * 60,
                      "  %s -> %s satır (%%%.1f korundu)"
                      % (format(report.get("rows_in", 0), ","),
                         format(report.get("rows_out", 0), ","),
                         report.get("retention_pct", 0.0))]
            for stage in report.get("stages", []):
                lines.append("  %-24s -%s" % (stage["stage"], format(stage["removed"], ",")))
            for corr in report.get("correlations", []):
                lines.append("  korelasyon %s: r=%s [%s]"
                             % ("/".join(corr["pair"]), corr.get("actual_r"),
                                "GEÇTİ" if corr.get("pass") else "KALDI"))

        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", "\n".join(lines))
        self.detail_box.configure(state="disabled")
