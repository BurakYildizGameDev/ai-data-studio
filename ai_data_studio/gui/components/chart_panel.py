"""Grafik paneli - Matplotlib Agg backend ve CTkImage render mekanizması.

Tasarım kararı: Matplotlib'in interaktif backend'i (TkAgg) PyInstaller ile paketlendiğinde
CustomTkinter ile çakışabildiği için `matplotlib.use("Agg")` doğrudan çağrılır;
tüm grafikler bellekte PNG'ye çizilerek CTkImage olarak gösterilir.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # İnteraktif olmayan bellek içi Agg render motoru

import customtkinter as ctk  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

from ...i18n import t  # noqa: E402

log = logging.getLogger(__name__)

DARK_BG = "#242424"
DARK_FG = "#d4d4d4"
GRID_COLOR = "#3f3f3f"
ACCENT = "#4fc3f7"
ACCENT_2 = "#81c784"
ACCENT_WARN = "#e57373"


def render_chart_to_ctkimage(fig, size: Tuple[int, int] = (400, 300)) -> ctk.CTkImage:
    """Figure -> bellekte PNG -> PIL Image -> CTkImage."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    buf.seek(0)
    pil_img = Image.open(buf)
    pil_img.load()          # buffer kapanmadan once pikselleri oku
    buf.close()
    return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)


def _new_figure(width: float = 4.0, height: float = 3.0):
    fig, ax = plt.subplots(figsize=(width, height), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
    ax.tick_params(colors=DARK_FG, labelsize=8)
    ax.xaxis.label.set_color(DARK_FG)
    ax.yaxis.label.set_color(DARK_FG)
    ax.title.set_color(DARK_FG)
    ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.6)
    return fig, ax


def make_retention_chart(report: Dict[str, Any], size=(420, 260)) -> Optional[ctk.CTkImage]:
    """Validasyon aşamalarının kaç satır elediğini gösteren yatay bar grafiği."""
    stages = report.get("stages") or []
    if not stages:
        return None
    fig, ax = _new_figure(4.2, 2.6)
    try:
        labels = [s["stage"] for s in stages][::-1]
        removed = [s["removed"] for s in stages][::-1]
        ax.barh(labels, removed, color=ACCENT_WARN, height=0.55)
        ax.set_xlabel(t("charts.retention.x_label"), fontsize=8)
        ax.set_title(t("charts.retention.title"), fontsize=10)
        for i, value in enumerate(removed):
            if value:
                ax.text(value, i, " %s" % format(value, ","), va="center",
                        color=DARK_FG, fontsize=7)
        fig.tight_layout()
        return render_chart_to_ctkimage(fig, size)
    finally:
        plt.close(fig)


def make_distribution_chart(df, column: str, size=(420, 260)) -> Optional[ctk.CTkImage]:
    """Tek bir sayısal kolonun histogramı."""
    if df is None or column not in df.columns:
        return None
    fig, ax = _new_figure(4.2, 2.6)
    try:
        series = df[column].dropna()
        if series.empty:
            return None
        ax.hist(series, bins=40, color=ACCENT, edgecolor=DARK_BG, linewidth=0.4)
        ax.set_title(t("charts.distribution.title", column=column), fontsize=10)
        ax.set_xlabel(column, fontsize=8)
        ax.set_ylabel(t("charts.distribution.y_label"), fontsize=8)
        fig.tight_layout()
        return render_chart_to_ctkimage(fig, size)
    except Exception as exc:
        log.warning("Dağılım grafiği çizilemedi (%s): %s", column, exc)
        return None
    finally:
        plt.close(fig)


def make_correlation_chart(df, columns: List[str], size=(420, 320)) -> Optional[ctk.CTkImage]:
    """Sayısal kolonların korelasyon işi haritası."""
    usable = [c for c in columns if c in (df.columns if df is not None else [])]
    if df is None or len(usable) < 2:
        return None
    fig, ax = _new_figure(4.2, 3.2)
    try:
        corr = df[usable].corr(numeric_only=True)
        image = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr.columns)))
        ax.set_yticks(range(len(corr.columns)))
        ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=7)
        ax.set_yticklabels(corr.columns, fontsize=7)
        ax.grid(False)
        for i in range(len(corr.columns)):
            for j in range(len(corr.columns)):
                value = corr.values[i, j]
                ax.text(j, i, "%.2f" % value, ha="center", va="center", fontsize=6,
                        color="#101010" if abs(value) > 0.5 else DARK_FG)
        colorbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        colorbar.ax.tick_params(colors=DARK_FG, labelsize=7)
        ax.set_title(t("charts.correlation.title"), fontsize=10)
        fig.tight_layout()
        return render_chart_to_ctkimage(fig, size)
    except Exception as exc:
        log.warning("Korelasyon grafiği çizilemedi: %s", exc)
        return None
    finally:
        plt.close(fig)


class ChartPanel(ctk.CTkFrame):
    """Üretilen grafikleri yan yana gösteren kaydırılabilir panel."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text=t("charts.panel.title"),
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, sticky="w")

        # Tablo secici yalnizca cok tablolu kosuda gorunur; tek tabloda panel
        # eskisiyle birebir ayni kalir.
        self.table_menu = ctk.CTkOptionMenu(header, values=[""], width=180,
                                            command=self._on_table_change)
        self.table_menu.grid(row=0, column=2, sticky="e")
        self.table_menu.grid_remove()

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
        self.scroll.grid_columnconfigure(0, weight=1)

        self.placeholder = ctk.CTkLabel(
            self.scroll, text=t("charts.panel.placeholder"), text_color="#8a8a8a")
        self.placeholder.grid(row=0, column=0, pady=30)
        self._images: List[ctk.CTkImage] = []   # GC'ye karsi referans tut
        self._tables: Dict[str, Any] = {}
        self._contract = None
        self._report: Dict[str, Any] = {}

    def clear(self) -> None:
        for widget in self.scroll.winfo_children():
            widget.destroy()
        self._images.clear()
        self._tables = {}
        self._contract = None
        self._report = {}
        self.table_menu.grid_remove()
        self.placeholder = ctk.CTkLabel(
            self.scroll, text=t("charts.panel.placeholder"), text_color="#8a8a8a")
        self.placeholder.grid(row=0, column=0, pady=30)

    def render(self, df, schema, report: Dict[str, Any], contract=None,
               tables: Optional[Dict[str, Any]] = None) -> None:
        """Temiz veri + rapordan grafikleri üretip yerleştirir.

        ``contract`` ve ``tables`` verilirse (çok tablolu koşu) panelin üstünde
        bir tablo seçici belirir ve seçim değişince yalnız grafikler yeniden
        çizilir. Tek tabloda ikisi de ``None`` gelir, davranış değişmez.
        """
        self._contract = contract
        self._report = report or {}
        self._tables = dict(tables or {})

        names = list(self._tables) if (contract is not None and len(self._tables) > 1) else []
        if names:
            # Uretim sirasi kullaniciya en anlamli sira: once kok, sonra cocuklar.
            try:
                names = [n for n in contract.generation_order() if n in self._tables]
            except Exception:
                names.sort()
            self.table_menu.configure(values=names)
            self.table_menu.set(contract.root_table if contract.root_table in names
                                else names[0])
            self.table_menu.grid()
        else:
            self.table_menu.grid_remove()

        self._render_charts(df, schema, report)

    def _on_table_change(self, name: str) -> None:
        """Tablo seçimi değişti - yalnız grafikleri yeniden çiz."""
        if not self._tables or self._contract is None:
            return
        table_df = self._tables.get(name)
        if table_df is None:
            return
        try:
            schema = self._contract.table(name)
        except Exception as exc:
            log.warning("Tablo şeması bulunamadı (%s): %s", name, exc)
            return
        # Ayiklama grafigi tabloya ozgu: iliskiselde her tablonun kendi raporu var.
        table_report = (self._report.get("tables") or {}).get(name) or self._report
        self._render_charts(table_df, schema, table_report)

    def _render_charts(self, df, schema, report: Dict[str, Any]) -> None:
        # Widget'lari once yok et, SONRA yeni listeyi doldur: _images referanslari
        # CTkImage'lari cop toplayicidan koruyor, sirayi bozmak bellegi buyutur.
        for widget in self.scroll.winfo_children():
            widget.destroy()
        self._images.clear()

        charts: List[Tuple[str, Optional[ctk.CTkImage]]] = [
            (t("charts.retention.title"), make_retention_chart(report)),
            (t("charts.correlation.title"), make_correlation_chart(df, schema.numeric_columns)),
        ]
        for column in schema.numeric_columns[:3]:
            charts.append((column, make_distribution_chart(df, column)))

        row = 0
        for title, image in charts:
            if image is None:
                continue
            self._images.append(image)
            label = ctk.CTkLabel(self.scroll, image=image, text="")
            label.grid(row=row, column=0, pady=8)
            row += 1

        if row == 0:
            ctk.CTkLabel(self.scroll, text=t("charts.panel.empty"),
                         text_color="#8a8a8a").grid(row=0, column=0, pady=30)
