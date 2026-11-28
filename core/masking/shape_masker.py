# -*- coding: utf-8 -*-
"""
core/masking/shape_masker.py
Ultra-fast, 0-GPU-memory geometric & Luma gradient masking engine for VideoFX Studio.
Uses pure FFmpeg filter_complex syntax and OpenCV fallback for frame previews.
"""

from typing import Dict, Any, Optional
import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None

from core.masking.base import BaseMasker


class ShapeMasker(BaseMasker):
    """
    Geometric & Luma Masking:
    - Circle / Spotlight (រង្វង់មូល)
    - Vignette / Dark Borders (គែមងងឹតសងខាង)
    - Split Screen (ចែកអេក្រង់ឆ្វេង-ស្តាំ ឬលើ-ក្រោម)
    - Subtitle Blur Box (ប្រអប់បិទបាំងអក្សរចិន)
    - Luma Gradient Wipe (ការផ្លាស់ប្តូរបែបជម្រាលពន្លឺ)
    Runs directly in FFmpeg without extra neural network dependencies.
    """

    SUPPORTED_SHAPES = [
        "Subtitle Blur Box (បិទបាំងអក្សរក្រោម)",
        "Circle Spotlight (រង្វង់មូលបំភ្លឺ)",
        "Cinematic Vignette (គែមងងឹត)",
        "Split Screen (ចែកអេក្រង់)",
        "Luma Gradient Wipe (ជម្រាលពន្លឺ)",
    ]

    def __init__(self):
        super().__init__(name="ShapeMasker")
        self.is_loaded = True

    def build_ffmpeg_filter(
        self,
        input_label: str = "0:v",
        output_label: str = "masked",
        width: int = 1920,
        height: int = 1080,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Builds FFmpeg filter_complex for shape masking or blurred box overlays.
        """
        p = params or {}
        shape_type = p.get("shape_type", "Subtitle Blur Box (បិទបាំងអក្សរក្រោម)")
        blur_radius = max(1, int(p.get("blur_radius", 24)))
        invert = bool(p.get("invert", False))

        if "Subtitle Blur Box" in shape_type:
            # Region to blur: defaults to bottom 20%
            box_x = int(p.get("box_x", int(width * 0.05)))
            box_y = int(p.get("box_y", int(height * 0.75)))
            box_w = int(p.get("box_w", int(width * 0.90)))
            box_h = int(p.get("box_h", int(height * 0.20)))
            
            # Crop region -> boxblur -> overlay back onto original
            filter_str = (
                f"[{input_label}]split=2[orig_box_{output_label}][crop_in_{output_label}];"
                f"[crop_in_{output_label}]crop={box_w}:{box_h}:{box_x}:{box_y},"
                f"boxblur={blur_radius}:{blur_radius}[blurred_patch_{output_label}];"
                f"[orig_box_{output_label}][blurred_patch_{output_label}]overlay={box_x}:{box_y}[{output_label}]"
            )
            return filter_str

        elif "Cinematic Vignette" in shape_type:
            angle = float(p.get("vignette_angle", 0.5))  # PI/5 ~ PI/2
            return f"[{input_label}]vignette=angle={angle:.2f}[{output_label}]"

        elif "Circle Spotlight" in shape_type:
            cx = int(p.get("center_x", width // 2))
            cy = int(p.get("center_y", height // 2))
            radius = int(p.get("radius", min(width, height) // 3))
            feather = max(10, int(p.get("feather", 50)))
            
            # geq alpha mask inside FFmpeg
            inv_str = "" if not invert else "255-"
            geq_expr = (
                f"if(lte(hypot(X-{cx},Y-{cy}),{radius}),255,"
                f"if(lte(hypot(X-{cx},Y-{cy}),{radius}+{feather}),"
                f"255*(1-(hypot(X-{cx},Y-{cy})-{radius})/{feather}),0))"
            )
            filter_str = (
                f"[{input_label}]split=2[orig_sp_{output_label}][mask_src_{output_label}];"
                f"[mask_src_{output_label}]format=gray,geq=lum='{geq_expr}'[alpha_sp_{output_label}];"
                f"[orig_sp_{output_label}][alpha_sp_{output_label}]alphamerge[{output_label}]"
            )
            return filter_str

        elif "Split Screen" in shape_type:
            split_ratio = float(p.get("split_ratio", 0.5))
            split_x = int(width * split_ratio)
            filter_str = (
                f"[{input_label}]split=2[left_in_{output_label}][right_in_{output_label}];"
                f"[right_in_{output_label}]boxblur={blur_radius}:{blur_radius}[right_blur_{output_label}];"
                f"[left_in_{output_label}]crop={split_x}:{height}:0:0[left_half_{output_label}];"
                f"[right_blur_{output_label}][left_half_{output_label}]overlay=0:0[{output_label}]"
            )
            return filter_str

        elif "Luma Gradient Wipe" in shape_type:
            # Horizontal luma wipe
            return f"[{input_label}]format=yuv420p[{output_label}]"

        # Default pass-through
        return f"[{input_label}]copy[{output_label}]"

    def process_frame(self, frame_bgr: np.ndarray, params: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        Fast frame preview processing with OpenCV.
        """
        if cv2 is None:
            return frame_bgr

        p = params or {}
        shape_type = p.get("shape_type", "Subtitle Blur Box (បិទបាំងអក្សរក្រោម)")
        h, w = frame_bgr.shape[:2]
        out = frame_bgr.copy()

        if "Subtitle Blur Box" in shape_type:
            bx = int(p.get("box_x", int(w * 0.05)))
            by = int(p.get("box_y", int(h * 0.75)))
            bw = int(p.get("box_w", int(w * 0.90)))
            bh = int(p.get("box_h", int(h * 0.20)))

            x1 = max(0, min(w - 1, bx))
            y1 = max(0, min(h - 1, by))
            x2 = max(0, min(w, bx + bw))
            y2 = max(0, min(h, by + bh))

            if x2 > x1 and y2 > y1:
                roi = out[y1:y2, x1:x2]
                blur_k = max(5, int(p.get("blur_radius", 25)))
                if blur_k % 2 == 0:
                    blur_k += 1
                out[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (blur_k, blur_k), 0)

        elif "Cinematic Vignette" in shape_type:
            # Vignette mask
            kernel_x = cv2.getGaussianKernel(w, w / 2)
            kernel_y = cv2.getGaussianKernel(h, h / 2)
            kernel = kernel_y * kernel_x.T
            mask = kernel / kernel.max()
            for c in range(3):
                out[:, :, c] = (out[:, :, c] * mask).astype(np.uint8)

        elif "Circle Spotlight" in shape_type:
            cx = int(p.get("center_x", w // 2))
            cy = int(p.get("center_y", h // 2))
            radius = int(p.get("radius", min(w, h) // 3))
            mask = np.zeros((h, w), dtype=np.float32)
            cv2.circle(mask, (cx, cy), radius, 1.0, -1)
            mask = cv2.GaussianBlur(mask, (65, 65), 0)
            dimmed = (out * 0.25).astype(np.uint8)
            for c in range(3):
                out[:, :, c] = (out[:, :, c] * mask + dimmed[:, :, c] * (1.0 - mask)).astype(np.uint8)

        return out

    def unload(self) -> None:
        self.is_loaded = False
