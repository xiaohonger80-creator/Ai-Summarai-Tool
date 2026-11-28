import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

LUTS_DIR = Path("assets/luts")


class LUTEngine:
    """
    3D Color LUT Engine for VideoFX Studio:
    - Scans assets/luts/ for standard 3D .cube files.
    - Auto-generates 6 cinematic 17x17x17 .cube presets on first run if missing.
    - Generates FFmpeg filter_complex syntax supporting 0% to 100% intensity blending.
    """

    PRESET_NAMES = [
        "Cinematic_Teal_Orange.cube",
        "Kodak_Vintage_Film.cube",
        "Moody_Dark_Drama.cube",
        "Warm_Golden_Hour.cube",
        "Noir_High_Contrast.cube",
        "Vivid_Social_Pop.cube",
    ]

    def __init__(self, luts_dir: Path = LUTS_DIR):
        self.luts_dir = Path(luts_dir)
        self.luts_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_built_in_presets()

    @staticmethod
    def escape_ffmpeg_path(path: str) -> str:
        r"""
        Escapes Windows backslashes and drive letter colons for FFmpeg filter syntax.
        e.g., C:\path\to\lut.cube -> C\:/path/to/lut.cube
        """
        p_str = str(Path(path).resolve()).replace("\\", "/")
        return p_str.replace(":", r"\:")

    def _ensure_built_in_presets(self):
        """Generates 6 production-grade 17x17x17 3D .cube LUT files if missing."""
        existing = list(self.luts_dir.glob("*.cube"))
        if len(existing) >= 6:
            return

        size = 17
        step = size - 1

        def clamp(v: float) -> float:
            return max(0.0, min(1.0, float(v)))

        # 1. Cinematic Teal & Orange
        def f_teal_orange(r, g, b):
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            # Shadows: boost teal (cyan-blue)
            r_out = r + (1.0 - luma) * (-0.12) + luma * 0.18
            g_out = g + (1.0 - luma) * 0.04 + luma * 0.08
            b_out = b + (1.0 - luma) * 0.22 - luma * 0.14
            # S-curve contrast
            r_out = r_out * r_out * (3.0 - 2.0 * r_out)
            g_out = g_out * g_out * (3.0 - 2.0 * g_out)
            b_out = b_out * b_out * (3.0 - 2.0 * b_out)
            return clamp(r_out), clamp(g_out), clamp(b_out)

        # 2. Kodak Vintage Film
        def f_kodak(r, g, b):
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            # Lifted blacks (matte shadows)
            r_out = 0.06 + 0.88 * r + luma * 0.08
            g_out = 0.05 + 0.88 * g + luma * 0.04
            b_out = 0.08 + 0.82 * b - luma * 0.06
            # Film warmth
            r_out += 0.03
            g_out += 0.01
            return clamp(r_out), clamp(g_out), clamp(b_out)

        # 3. Moody Dark Drama
        def f_moody(r, g, b):
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            # Crushed shadows, desaturated cold tones
            sat = 0.65
            r_sat = luma + (r - luma) * sat
            g_sat = luma + (g - luma) * sat
            b_sat = luma + (b - luma) * sat
            # Deep contrast
            r_out = pow(r_sat, 1.25) * 0.95
            g_out = pow(g_sat, 1.25) * 0.98
            b_out = pow(b_sat, 1.20) * 1.05
            return clamp(r_out), clamp(g_out), clamp(b_out)

        # 4. Warm Golden Hour
        def f_golden(r, g, b):
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            r_out = r * 1.15 + 0.05
            g_out = g * 1.04 + 0.02
            b_out = b * 0.88 - 0.02
            # Rich warm contrast
            r_out = 0.5 + 1.12 * (r_out - 0.5)
            g_out = 0.5 + 1.08 * (g_out - 0.5)
            b_out = 0.5 + 1.02 * (b_out - 0.5)
            return clamp(r_out), clamp(g_out), clamp(b_out)

        # 5. Noir High Contrast (Black & White Cinema)
        def f_noir(r, g, b):
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            # S-curve B&W
            val = luma * luma * (3.0 - 2.0 * luma)
            val = clamp(0.5 + 1.28 * (val - 0.5))
            return val, val, val

        # 6. Vivid Social Pop
        def f_vivid(r, g, b):
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            sat = 1.35
            r_out = clamp(luma + (r - luma) * sat)
            g_out = clamp(luma + (g - luma) * sat)
            b_out = clamp(luma + (b - luma) * sat)
            # Slight punch
            r_out = clamp(r_out * 1.04)
            g_out = clamp(g_out * 1.04)
            b_out = clamp(b_out * 1.04)
            return r_out, g_out, b_out

        presets = [
            ("Cinematic_Teal_Orange.cube", "Cinematic Teal Orange", f_teal_orange),
            ("Kodak_Vintage_Film.cube", "Kodak Vintage Film", f_kodak),
            ("Moody_Dark_Drama.cube", "Moody Dark Drama", f_moody),
            ("Warm_Golden_Hour.cube", "Warm Golden Hour", f_golden),
            ("Noir_High_Contrast.cube", "Noir High Contrast", f_noir),
            ("Vivid_Social_Pop.cube", "Vivid Social Pop", f_vivid),
        ]

        for fname, title, fn in presets:
            target_file = self.luts_dir / fname
            if not target_file.exists():
                self._write_cube_file(target_file, title, size, fn)

    def _write_cube_file(self, out_path: Path, title: str, size: int, func):
        step = size - 1
        lines = [
            f"# VideoFX Studio 3D LUT: {title}",
            f'TITLE "{title}"',
            f"LUT_3D_SIZE {size}",
            "DOMAIN_MIN 0.0 0.0 0.0",
            "DOMAIN_MAX 1.0 1.0 1.0",
        ]
        # Standard .cube order: blue outer loop, green middle, red inner
        for b_idx in range(size):
            b_val = b_idx / step
            for g_idx in range(size):
                g_val = g_idx / step
                for r_idx in range(size):
                    r_val = r_idx / step
                    ro, go, bo = func(r_val, g_val, b_val)
                    lines.append(f"{ro:.6f} {go:.6f} {bo:.6f}")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def get_available_luts(self) -> List[str]:
        """Returns filenames of all available .cube LUTs in assets/luts/."""
        return [c.name for c in sorted(self.luts_dir.glob("*.cube"))]

    def get_lut_path(self, lut_name: str) -> Optional[str]:
        """Resolves lut_name (or filename) to absolute path string."""
        if not lut_name:
            return None
        p = Path(lut_name)
        if p.is_file() and p.exists():
            return str(p.resolve())
        candidate = self.luts_dir / lut_name
        if candidate.exists():
            return str(candidate.resolve())
        # Try matching by stem
        for c in self.luts_dir.glob("*.cube"):
            if c.stem.lower() == p.stem.lower() or c.name.lower() == lut_name.lower():
                return str(c.resolve())
        return None

    def build_ffmpeg_filter(
        self,
        lut_name: str,
        intensity: float = 1.0,
        input_label: str = "0:v",
        output_label: str = "lut_out"
    ) -> str:
        """Alias resolving name to path before calling build_lut_filter."""
        path = self.get_lut_path(lut_name)
        return self.build_lut_filter(path or "", intensity=intensity, in_label=input_label, out_label=output_label)

    def import_custom_lut(self, src_path: str) -> Optional[str]:
        """Alias for import_lut."""
        return self.import_lut(src_path)

    def list_luts(self) -> List[Dict[str, Any]]:
        """Returns list of available .cube files with path and friendly name."""
        cubes = sorted(self.luts_dir.glob("*.cube"))
        items = []
        for c in cubes:
            name = c.stem.replace("_", " ")
            items.append({
                "name": name,
                "filename": c.name,
                "path": str(c.resolve()),
            })
        return items

    def import_lut(self, src_path: str) -> Optional[str]:
        """Imports an external .cube file into assets/luts/."""
        src = Path(src_path)
        if src.exists() and src.suffix.lower() == ".cube":
            dest = self.luts_dir / src.name
            shutil.copy2(src, dest)
            return str(dest.resolve())
        return None

    def build_lut_filter(
        self,
        lut_path: str,
        intensity: float = 1.0,
        in_label: str = "0:v",
        out_label: str = "lut_out"
    ) -> str:
        """
        Builds FFmpeg filter syntax supporting 0% to 100% LUT intensity blending.
        Uses: split + lut3d + blend=all_expr='A*(1-W)+B*W'
        """
        if not lut_path or not Path(lut_path).exists():
            return f"[{in_label}]copy[{out_label}]"

        escaped = self.escape_ffmpeg_path(lut_path)
        intensity = max(0.0, min(1.0, float(intensity)))

        if intensity >= 0.999:
            # 100% intensity direct application
            return f"[{in_label}]lut3d='{escaped}'[{out_label}]"
        elif intensity <= 0.001:
            # 0% intensity pass-through
            return f"[{in_label}]copy[{out_label}]"
        else:
            # Blend between original and graded
            w = round(intensity, 3)
            filter_str = (
                f"[{in_label}]split=2[lut_orig][lut_in];"
                f"[lut_in]lut3d='{escaped}'[lut_graded];"
                f"[lut_orig][lut_graded]blend=all_expr='A*(1-{w})+B*{w}':shortest=1[{out_label}]"
            )
            return filter_str
