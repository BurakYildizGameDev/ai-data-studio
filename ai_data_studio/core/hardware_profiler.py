# -*- coding: utf-8 -*-
"""Sistem donanımını (CPU, RAM, GPU, VRAM) tarayan ve en uygun LLM modelini öneren profil motoru.

Bu modül kullanıcının makinesini analiz ederek:
1. Donanım seviyesini (ULTRA_LOW, MID, HIGH, ENTERPRISE) belirler.
2. Ekran kartı varsa (NVIDIA CUDA / Apple Silicon) VRAM miktarını okur.
3. Çevrimdışı kullanım için en optimize Ollama modelini önerir.
4. Donanıma uygun maksimum güvenli sentetik satır limitini hesaplar.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Donanım Kademeleri
TIER_ULTRA_LOW = "ULTRA_LOW"    # Entegre GPU veya <8 GB RAM
TIER_MID = "MID"                # 4-6 GB VRAM veya 16 GB RAM (CPU)
TIER_HIGH = "HIGH"              # 8-12 GB VRAM (Örn: RTX 4070 / 5070 Ti)
TIER_ENTERPRISE = "ENTERPRISE"  # 16+ GB VRAM veya İş İstasyonu

# Önerilen Modeller
MODEL_1_5B = "qwen2.5-coder:1.5b"
MODEL_3B = "qwen2.5-coder:3b"
MODEL_7B = "qwen2.5-coder:7b"
MODEL_14B = "qwen2.5-coder:14b"
MODEL_32B = "qwen2.5-coder:32b"


@dataclass
class HardwareProfile:
    """Sistem donanım özeti ve model önerileri."""
    cpu_name: str
    cpu_physical_cores: int
    cpu_logical_cores: int
    ram_total_gb: float
    ram_available_gb: float
    has_gpu: bool
    gpu_name: str
    vram_total_gb: float
    vram_free_gb: float
    hardware_tier: str
    recommended_model: str
    execution_mode: str  # "gpu_cuda", "gpu_metal", "cpu_only"
    recommended_row_limit: int
    notes: str

    def to_dict(self) -> dict:
        return {
            "cpu_name": self.cpu_name,
            "cpu_cores": f"{self.cpu_physical_cores} fiziksel / {self.cpu_logical_cores} mantıksal",
            "ram_total_gb": round(self.ram_total_gb, 2),
            "ram_available_gb": round(self.ram_available_gb, 2),
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name,
            "vram_total_gb": round(self.vram_total_gb, 2),
            "vram_free_gb": round(self.vram_free_gb, 2),
            "hardware_tier": self.hardware_tier,
            "recommended_model": self.recommended_model,
            "execution_mode": self.execution_mode,
            "recommended_row_limit": self.recommended_row_limit,
            "notes": self.notes,
        }


def _detect_nvidia_gpu() -> tuple[bool, str, float, float]:
    """nvidia-smi aracılığıyla NVIDIA GPU ve VRAM miktarını okur."""
    if shutil.which("nvidia-smi") is None:
        return False, "Yok / Entegre", 0.0, 0.0

    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free",
            "--format=csv,noheader,nounits"
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            shell=(platform.system() == "Windows")
        )
        if res.returncode == 0 and res.stdout.strip():
            first_line = res.stdout.strip().splitlines()[0]
            parts = first_line.split(",")
            if len(parts) >= 3:
                name = parts[0].strip()
                total_mb = float(parts[1].strip())
                free_mb = float(parts[2].strip())
                return True, name, total_mb / 1024.0, free_mb / 1024.0
    except Exception as exc:
        log.debug("nvidia-smi okuma hatası: %s", exc)

    return False, "Yok / Entegre", 0.0, 0.0


def _detect_torch_cuda() -> tuple[bool, str, float, float]:
    """PyTorch yüklüyse doğrudan CUDA belleğini kontrol eder."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            total_gb = props.total_memory / (1024 ** 3)
            # PyTorch'ta anlık ayrılmış bellek
            reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
            free_gb = max(0.0, total_gb - reserved)
            return True, name, total_gb, free_gb
    except Exception:
        pass
    return False, "", 0.0, 0.0


def profile_hardware() -> HardwareProfile:
    """Mevcut sistem donanımını profiller ve en uygun modeli önerir."""
    import psutil

    # 1. CPU
    cpu_name = platform.processor() or platform.machine() or "Bilinmeyen CPU"
    cores_phys = psutil.cpu_count(logical=False) or 2
    cores_log = psutil.cpu_count(logical=True) or cores_phys

    # 2. RAM
    vm = psutil.virtual_memory()
    ram_total_gb = vm.total / (1024 ** 3)
    ram_avail_gb = vm.available / (1024 ** 3)

    # 3. GPU / VRAM
    has_gpu, gpu_name, vram_total_gb, vram_free_gb = _detect_nvidia_gpu()
    if not has_gpu:
        has_gpu, gpu_name, vram_total_gb, vram_free_gb = _detect_torch_cuda()

    # 4. Kademe ve Model Tavsiyesi
    if has_gpu and vram_total_gb >= 15.0:
        tier = TIER_ENTERPRISE
        model = MODEL_14B
        mode = "gpu_cuda"
        limit = 1_000_000
        notes = f"Yüksek Seviye GPU ({gpu_name}, {vram_total_gb:.1f} GB VRAM). 14B ve 32B modeller tam CUDA hızında çalışabilir."
    elif has_gpu and vram_total_gb >= 7.5:
        tier = TIER_HIGH
        model = MODEL_7B
        mode = "gpu_cuda"
        limit = 500_000
        notes = f"Güçlü GPU ({gpu_name}, {vram_total_gb:.1f} GB VRAM). 7B model sıfır gecikmeyle tam ekran kartında çalışır."
    elif (has_gpu and vram_total_gb >= 3.5) or ram_total_gb >= 15.0:
        tier = TIER_MID
        model = MODEL_7B if has_gpu else MODEL_3B
        mode = "gpu_cuda" if has_gpu else "cpu_only"
        limit = 100_000
        notes = f"Orta Seviye Sistem ({vram_total_gb:.1f} GB VRAM / {ram_total_gb:.1f} GB RAM). 7B Q4 veya 3B model önerilir."
    else:
        tier = TIER_ULTRA_LOW
        model = MODEL_1_5B
        mode = "cpu_only"
        limit = 25_000
        notes = "Düşük Donanım / Entegre Grafik. 986 MB'lık Qwen 1.5B modeli CPU modunda güvenle çalıştırılmalıdır."

    return HardwareProfile(
        cpu_name=cpu_name,
        cpu_physical_cores=cores_phys,
        cpu_logical_cores=cores_log,
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_avail_gb,
        has_gpu=has_gpu,
        gpu_name=gpu_name,
        vram_total_gb=vram_total_gb,
        vram_free_gb=vram_free_gb,
        hardware_tier=tier,
        recommended_model=model,
        execution_mode=mode,
        recommended_row_limit=limit,
        notes=notes,
    )


def format_hardware_report(prof: Optional[HardwareProfile] = None) -> str:
    """Terminal veya loglar için insan tarafından okunabilir donanım raporu."""
    if prof is None:
        prof = profile_hardware()

    gpu_str = f"{prof.gpu_name} ({prof.vram_total_gb:.1f} GB VRAM)" if prof.has_gpu else "Yok / Entegre Grafik"

    lines = [
        "============================================================",
        "          DONANIM PROFİLİ VE MODEL TAVSİYE RAPORU           ",
        "============================================================",
        f"  İşlemci (CPU):    {prof.cpu_name}",
        f"  Çekirdekler:      {prof.cpu_physical_cores} Fiziksel / {prof.cpu_logical_cores} Mantıksal",
        f"  Sistem RAM:       {prof.ram_total_gb:.1f} GB (Kullanılabilir: {prof.ram_available_gb:.1f} GB)",
        f"  Grafik Kartı:     {gpu_str}",
        f"  Donanım Kademesi: {prof.hardware_tier}",
        f"  Çalışma Modu:     {prof.execution_mode.upper()}",
        f"  Önerilen Model:   {prof.recommended_model}",
        f"  Önerilen Satır:   {prof.recommended_row_limit:,} Satıra kadar optimize",
        f"  Açıklama:         {prof.notes}",
        "============================================================",
    ]
    return "\n".join(lines)
