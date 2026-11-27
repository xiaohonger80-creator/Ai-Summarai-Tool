# -*- coding: utf-8 -*-
"""
Ai Summarai — 20+ Cinematic Adjustments & LUT Presets Catalog
--------------------------------------------------------------
Curated FFmpeg color grading, film grain, mood, and anti-copyright LUT filters.
All filter chains use native built-in FFmpeg video filters (eq, colorbalance,
hue, curves, noise, unsharp, vignette) for 100% reliability on Windows/macOS/Linux
without external .cube file dependencies.
"""

from typing import Dict, List, Any


LUT_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "none",
        "name": "Original (ធម្មជាតិ / ដើម)",
        "short": "Original",
        "category": "Original",
        "desc": "រក្សាពណ៌ដើមនៃវីដេអូ ១០០%",
        "swatch": ("#334155", "#64748B"),
        "preview_tint": (0, 0, 0, 0),
        "ffmpeg_vf": "",
    },
    {
        "id": "cinematic",
        "name": "🎬 Cinematic (ភាពយន្ត)",
        "short": "Cinematic",
        "category": "Cinema",
        "desc": "ពណ៌ភាពយន្តស៊ីជម្រៅ Contrast ទន់ + ស្រមោលខៀវស្រាល",
        "swatch": ("#0F2027", "#2C5364"),
        "preview_tint": (18, 45, 72, 34),
        "ffmpeg_vf": "eq=contrast=1.08:brightness=-0.01:saturation=1.06:gamma=0.96,colorbalance=rs=-0.03:gs=0.01:bs=0.05:rh=0.04:gh=0.01:bh=-0.03",
    },
    {
        "id": "vibrant",
        "name": "🌈 Vibrant (ស្រស់ស្អាត)",
        "short": "Vibrant",
        "category": "Color",
        "desc": "បង្កើនភាពស្រស់ថ្លា និងពណ៌ច្បាស់លេចធ្លោសម្រាប់ TikTok/Reels",
        "swatch": ("#EC4899", "#F59E0B"),
        "preview_tint": (255, 165, 60, 26),
        "ffmpeg_vf": "eq=contrast=1.07:brightness=0.02:saturation=1.28:gamma=1.02,unsharp=5:5:0.45:5:5:0.0",
    },
    {
        "id": "vintage",
        "name": "🎞️ Vintage (បុរាណ)",
        "short": "Vintage",
        "category": "Retro",
        "desc": "ពណ៌បុរាណកក់ក្តៅ ដូចខ្សែភាពយន្តជំនាន់មុន",
        "swatch": ("#78350F", "#D97706"),
        "preview_tint": (165, 110, 48, 42),
        "ffmpeg_vf": "eq=contrast=0.95:brightness=0.02:saturation=0.78:gamma=1.06,colorbalance=rs=0.07:gs=0.02:bs=-0.08:rh=0.06:gh=0.03:bh=-0.07,noise=alls=3:allf=t+u",
    },
    {
        "id": "film_grain",
        "name": "📽️ Film Grain (គ្រាប់ហ្វីល)",
        "short": "Film Grain",
        "category": "Cinema",
        "desc": "បន្ថែមគ្រាប់ហ្វីលធម្មជាតិ 35mm ជួយបំបែក Visual Hash",
        "swatch": ("#27272A", "#71717A"),
        "preview_tint": (60, 56, 50, 28),
        "ffmpeg_vf": "eq=contrast=1.05:saturation=0.94:gamma=0.98,colorbalance=rs=0.02:bs=-0.02,noise=alls=5:allf=t+u",
    },
    {
        "id": "high_contrast",
        "name": "⚡ High Contrast (ពន្លឺច្បាស់ខ្លាំង)",
        "short": "High Contrast",
        "category": "Color",
        "desc": "បង្កើនភាពខុសគ្នានៃពន្លឺ និងស្រមោលឲ្យមុតច្បាស់",
        "swatch": ("#09090B", "#E4E4E7"),
        "preview_tint": (12, 12, 18, 36),
        "ffmpeg_vf": "eq=contrast=1.22:brightness=-0.02:saturation=1.10:gamma=0.95,unsharp=5:5:0.6:5:5:0.0",
    },
    {
        "id": "anti_copyright_lut",
        "name": "🛡️ Anti-Copyright LUT (កាត់ Copyright)",
        "short": "Anti-Copy LUT",
        "category": "Anti-Copy",
        "desc": "កែសម្រួល Color Matrix + Micro-Hue + Grain កាត់ផ្តាច់ Content ID",
        "swatch": ("#06B6D4", "#3B82F6"),
        "preview_tint": (0, 200, 235, 24),
        "ffmpeg_vf": "hue=h=3:s=1.08,eq=contrast=1.06:brightness=0.015:gamma=1.03,colorbalance=rs=0.03:gs=-0.01:bs=-0.03:rh=-0.02:bh=0.03,noise=alls=3:allf=t+u",
    },
    {
        "id": "soft_highlight",
        "name": "☁️ Soft Highlight (ពន្លឺទន់ភ្លន់)",
        "short": "Soft Highlight",
        "category": "Mood",
        "desc": "កាត់បន្ថយពន្លឺចាំងខ្លាំង ធ្វើឲ្យស្បែកតួអង្គមើលទៅទន់រលោង",
        "swatch": ("#FDE68A", "#F9A8D4"),
        "preview_tint": (255, 238, 220, 30),
        "ffmpeg_vf": "eq=contrast=0.94:brightness=0.035:saturation=1.04:gamma=1.06,colorbalance=rh=0.03:gh=0.02:bh=0.01",
    },
    {
        "id": "warm_retro",
        "name": "🌅 Warm Retro (អតីតកាលកក់ក្តៅ)",
        "short": "Warm Retro",
        "category": "Retro",
        "desc": "ពណ៌ទឹកក្រូចមាសកក់ក្តៅ បែបភាពយន្តហុងកុងឆ្នាំ ៩០",
        "swatch": ("#EA580C", "#FACC15"),
        "preview_tint": (220, 120, 30, 38),
        "ffmpeg_vf": "eq=contrast=1.04:brightness=0.01:saturation=1.12:gamma=1.02,colorbalance=rs=0.06:gs=0.02:bs=-0.07:rm=0.05:bm=-0.05,noise=alls=2:allf=t+u",
    },
    {
        "id": "cyberpunk",
        "name": "🌆 Cyberpunk (នីអុងសាយប័រ)",
        "short": "Cyberpunk",
        "category": "Mood",
        "desc": "ពណ៌ស្វាយ-ខៀវនីអុង ទាក់ទាញភ្នែកខ្លាំង",
        "swatch": ("#9333EA", "#06B6D4"),
        "preview_tint": (130, 30, 210, 40),
        "ffmpeg_vf": "eq=contrast=1.14:saturation=1.24:gamma=0.95,colorbalance=rs=-0.04:gs=-0.02:bs=0.10:rh=0.08:gh=-0.04:bh=0.08",
    },
    {
        "id": "drama_glow",
        "name": "✨ Drama Glow (រឿងភាគភ្លឺថ្លា)",
        "short": "Drama Glow",
        "category": "Cinema",
        "desc": "ពណ៌ភ្លឺស្រស់ថ្លាដូចរឿងភាគចិន/កូរ៉េពេញនិយម",
        "swatch": ("#38BDF8", "#F472B6"),
        "preview_tint": (235, 220, 255, 26),
        "ffmpeg_vf": "eq=contrast=1.03:brightness=0.03:saturation=1.14:gamma=1.05,colorbalance=rs=0.02:gs=0.01:bs=0.02:rh=0.03:gh=0.02:bh=0.03",
    },
    {
        "id": "teal_orange",
        "name": "🎥 Teal & Orange (ហូលីវូដ)",
        "short": "Teal & Orange",
        "category": "Cinema",
        "desc": "ស្ទីលពណ៌ភាពយន្ត Hollywood (ស្រមោលខៀវ-ពន្លឺទឹកក្រូច)",
        "swatch": ("#0D9488", "#F97316"),
        "preview_tint": (20, 115, 120, 34),
        "ffmpeg_vf": "eq=contrast=1.10:saturation=1.15:gamma=0.97,colorbalance=rs=-0.06:gs=0.02:bs=0.08:rh=0.08:gh=0.02:bh=-0.06",
    },
    {
        "id": "moody_dark",
        "name": "🌑 Moody Dark (ងងឹតអាថ៌កំបាំង)",
        "short": "Moody Dark",
        "category": "Mood",
        "desc": "បរិយាកាសងងឹតស្ងប់ស្ងាត់ សមសម្រាប់រឿងស៊ើបអង្កេត/រន្ធត់",
        "swatch": ("#0F172A", "#334155"),
        "preview_tint": (10, 18, 35, 58),
        "ffmpeg_vf": "eq=contrast=1.16:brightness=-0.05:saturation=0.80:gamma=0.90,colorbalance=rs=-0.03:gs=-0.01:bs=0.05",
    },
    {
        "id": "golden_hour",
        "name": "🌇 Golden Hour (ពន្លឺថ្ងៃលិចមាស)",
        "short": "Golden Hour",
        "category": "Color",
        "desc": "ពន្លឺពណ៌មាសស្រទន់ ដូចពេលថ្ងៃរៀបលិច",
        "swatch": ("#D97706", "#FDE047"),
        "preview_tint": (245, 175, 45, 36),
        "ffmpeg_vf": "eq=contrast=1.05:brightness=0.02:saturation=1.16:gamma=1.03,colorbalance=rs=0.05:gs=0.02:bs=-0.06:rh=0.09:gh=0.04:bh=-0.08",
    },
    {
        "id": "cool_breeze",
        "name": "❄️ Cool Breeze (ខៀវត្រជាក់ភ្នែក)",
        "short": "Cool Breeze",
        "category": "Mood",
        "desc": "ពណ៌ខៀវត្រជាក់ភ្លឺស្អាត ស្រស់ស្រាយ",
        "swatch": ("#0284C7", "#67E8F9"),
        "preview_tint": (40, 150, 225, 34),
        "ffmpeg_vf": "eq=contrast=1.04:brightness=0.01:saturation=1.05:gamma=1.01,colorbalance=rs=-0.05:gs=0.01:bs=0.08:rh=-0.04:gh=0.02:bh=0.06",
    },
    {
        "id": "pastel_dream",
        "name": "🌸 Pastel Dream (ពណ៌ផ្អែមស្រទន់)",
        "short": "Pastel Dream",
        "category": "Mood",
        "desc": "ពណ៌ផ្អែមទន់ភ្លន់ សម្រាប់រឿងស្នេហា/យុវវ័យ",
        "swatch": ("#F9A8D4", "#C4B5FD"),
        "preview_tint": (230, 170, 220, 32),
        "ffmpeg_vf": "eq=contrast=0.92:brightness=0.04:saturation=0.92:gamma=1.08,colorbalance=rs=0.04:gs=0.01:bs=0.04:rh=0.04:gh=0.02:bh=0.05",
    },
    {
        "id": "action_crisp",
        "name": "🔥 Action Crisp (ច្បាស់មុតរហ័ស)",
        "short": "Action Crisp",
        "category": "Cinema",
        "desc": "បង្កើនភាពមុតច្បាស់ Detail និង Contrast សម្រាប់រឿងវាយប្រហារ",
        "swatch": ("#DC2626", "#F97316"),
        "preview_tint": (180, 60, 25, 28),
        "ffmpeg_vf": "eq=contrast=1.15:brightness=-0.01:saturation=1.12:gamma=0.96,unsharp=5:5:0.85:5:5:0.0,colorbalance=rs=-0.02:bs=0.02",
    },
    {
        "id": "romance_rose",
        "name": "🌹 Romance Rose (រ៉ូមែនទិកផ្កាឈូក)",
        "short": "Romance Rose",
        "category": "Color",
        "desc": "ពណ៌ផ្កាឈូកកក់ក្តៅបែបរ៉ូមែនទិក",
        "swatch": ("#E11D48", "#FDA4AF"),
        "preview_tint": (225, 85, 130, 32),
        "ffmpeg_vf": "eq=contrast=1.02:brightness=0.02:saturation=1.10:gamma=1.04,colorbalance=rs=0.05:gs=-0.01:bs=0.02:rh=0.06:gh=0.01:bh=0.03",
    },
    {
        "id": "noir_bw",
        "name": "🖤 Noir B&W (ស-ខ្មៅ បុរាណ)",
        "short": "Noir B&W",
        "category": "Retro",
        "desc": "ពណ៌ស-ខ្មៅ កម្រិត Contrast ខ្ពស់បែបសិល្បៈភាពយន្ត",
        "swatch": ("#18181B", "#A1A1AA"),
        "preview_tint": (35, 35, 38, 65),
        "ffmpeg_vf": "hue=s=0,eq=contrast=1.24:brightness=-0.02:gamma=0.94,noise=alls=3:allf=t+u",
    },
    {
        "id": "anime_vivid",
        "name": "🎨 Anime Vivid (គំនូរជីវចលស្រស់)",
        "short": "Anime Vivid",
        "category": "Color",
        "desc": "ពណ៌ដិតភ្លឺស្រស់ និងបន្ទាត់ច្បាស់សម្រាប់ Animation/Donghua",
        "swatch": ("#6366F1", "#22D3EE"),
        "preview_tint": (80, 130, 255, 26),
        "ffmpeg_vf": "eq=contrast=1.10:brightness=0.02:saturation=1.34:gamma=1.02,unsharp=3:3:0.5:3:3:0.0",
    },
    {
        "id": "wuxia_jade",
        "name": "🐉 Wuxia Jade (គុនចិន ត្បូងមរកត)",
        "short": "Wuxia Jade",
        "category": "Cinema",
        "desc": "ពណ៌បៃតងត្បូងមរកត-មាស ដូចភាពយន្តគុនចិនបុរាណ",
        "swatch": ("#065F46", "#10B981"),
        "preview_tint": (16, 120, 88, 34),
        "ffmpeg_vf": "eq=contrast=1.08:brightness=-0.01:saturation=1.05:gamma=0.98,colorbalance=rs=-0.04:gs=0.05:bs=0.02:rh=0.04:gh=0.03:bh=-0.04",
    },
    {
        "id": "anti_copy_ultra",
        "name": "🔒 Anti-Copy Ultra Shift (បំបែកពណ៌ខ្លាំង)",
        "short": "Anti-Copy Ultra",
        "category": "Anti-Copy",
        "desc": "បង្វិល Hue + Gamma Curve + Grain ជួយគេចប្រព័ន្ធស្កេន Copyright ខ្លាំង",
        "swatch": ("#7C3AED", "#10B981"),
        "preview_tint": (90, 210, 175, 28),
        "ffmpeg_vf": "hue=h=-4:s=1.12,eq=contrast=1.09:brightness=0.02:gamma=1.05,colorbalance=rs=-0.03:gs=0.02:bs=0.04:rh=0.04:gh=-0.02:bh=-0.03,noise=alls=4:allf=t+u",
    },
]

LUT_PRESETS_BY_ID: Dict[str, Dict[str, Any]] = {p["id"]: p for p in LUT_PRESETS}


def get_lut_preset(preset_id: str) -> Dict[str, Any]:
    key = str(preset_id or "none").strip().lower()
    return LUT_PRESETS_BY_ID.get(key, LUT_PRESETS[0])


def get_lut_ffmpeg_filter(preset_id: str) -> str:
    return get_lut_preset(preset_id).get("ffmpeg_vf", "")


def get_lut_categories() -> List[str]:
    cats = ["All"]
    for p in LUT_PRESETS:
        c = p.get("category", "")
        if c and c not in cats:
            cats.append(c)
    return cats
