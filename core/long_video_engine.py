import gc
import os
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, List, Dict
from core.sentence_splitter import split_all_segments, clean_chinese_text, is_junk_text
from core.system_monitor import get_hardware_profile

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class LongVideoStreamEngine:
    CHUNK_SECONDS = 600  # ដំណើរការម្តង 10 នាទី (600 វិនាទី) ដើម្បីការពារ RAM និង Hard Disk
    OVERLAP_SEC = 15     # បន្ថែម 15 វិនាទី Overlap ដើម្បីការពារកុំឲ្យកាត់ផ្តាច់ប្រយោគចំកណ្តាលព្រំដែន 10 នាទី

    @staticmethod
    def _win_safe_path(path_str: str) -> str:
        """ការពារផ្លូវឯកសារវែងជ្រុល ឬមានតួអក្សរពិសេសលើ Windows"""
        p = str(Path(path_str).resolve())
        if os.name == "nt" and len(p) >= 240 and not p.startswith("\\\\?\\"):
            return "\\\\?\\" + p
        return p

    @classmethod
    def get_duration_sec(cls, video_path: str) -> float:
        safe_p = cls._win_safe_path(video_path)
        try:
            out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", safe_p
                ],
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            ).decode("utf-8", errors="ignore").strip()
            return max(1.0, float(out))
        except Exception:
            return 1.0

    @classmethod
    def has_audio_stream(cls, video_path: str) -> bool:
        safe_p = cls._win_safe_path(video_path)
        try:
            out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=codec_type",
                    "-of", "default=noprint_wrappers=1:nokey=1", safe_p
                ],
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            ).decode("utf-8", errors="ignore").strip()
            return "audio" in out.lower()
        except Exception:
            return False

    @classmethod
    def enforce_monotonic_slots(cls, segments: List[Dict], gap_ms: int = 25) -> List[Dict]:
        """
        ធានាថារាល់ប្រយោគទាំងអស់រត់តាមលំដាប់លំដោយ មិនជាន់ម៉ោងគ្នា (end_ms <= next_start_ms - 25ms)
        ដើម្បីការពារការជាន់សំឡេង ឬ Drift Timecode នៅម៉ោងទី 2+
        """
        if not segments:
            return []

        sorted_segs = sorted(segments, key=lambda s: int(s.get("start_ms", 0)))
        for i in range(len(sorted_segs) - 1):
            cur = sorted_segs[i]
            nxt = sorted_segs[i + 1]
            cur_s = int(cur.get("start_ms", 0))
            cur_e = max(cur_s + 150, int(cur.get("end_ms", cur_s + 150)))
            nxt_s = int(nxt.get("start_ms", 0))

            max_allowed_end = nxt_s - gap_ms
            if cur_e > max_allowed_end:
                if max_allowed_end >= cur_s + 150:
                    cur["end_ms"] = max_allowed_end
                else:
                    cur["end_ms"] = max(cur_s + 150, cur_e)
                    nxt["start_ms"] = cur["end_ms"] + gap_ms
                    if int(nxt.get("end_ms", 0)) <= nxt["start_ms"] + 150:
                        nxt["end_ms"] = nxt["start_ms"] + 350
            else:
                cur["end_ms"] = cur_e
        return sorted_segs

    @classmethod
    def _merge_or_append_segment(cls, all_segments: List[Dict], item: Dict, similarity_fn=None):
        if not all_segments:
            all_segments.append(item)
            return

        item_s = int(item["start_ms"])
        item_e = int(item["end_ms"])
        item_zh = clean_chinese_text(item.get("zh_text") or "")
        if not item_zh or is_junk_text(item_zh):
            return

        matched = False
        for prev in reversed(all_segments[-10:]):
            prev_s = int(prev["start_ms"])
            prev_e = int(prev["end_ms"])
            prev_zh = clean_chinese_text(prev.get("zh_text") or "")

            overlap_ms = max(0, min(item_e, prev_e) - max(item_s, prev_s))
            dur_min = max(1, min(item_e - item_s, prev_e - prev_s))
            time_overlap_ratio = overlap_ms / float(dur_min)

            is_text_sim = False
            if similarity_fn:
                is_text_sim = similarity_fn(prev_zh, item_zh)
            else:
                if prev_zh and item_zh:
                    if prev_zh == item_zh:
                        is_text_sim = True
                    else:
                        ratio = SequenceMatcher(None, prev_zh, item_zh).ratio()
                        if ratio >= 0.82:
                            is_text_sim = True
                        elif (prev_zh in item_zh or item_zh in prev_zh) and (min(len(prev_zh), len(item_zh)) / max(len(prev_zh), len(item_zh)) >= 0.80):
                            is_text_sim = True

            combined_dur = max(prev_e, item_e) - prev_s
            # បញ្ចូលតែប្រយោគស្រដៀងគ្នា ហើយមិនលើសពី 4.2 វិនាទី (ដើម្បីកុំឱ្យប្រយោគវែងពេក)
            if combined_dur <= 4200 and ((time_overlap_ratio > 0.40 and is_text_sim) or (abs(item_s - prev_e) <= 350 and is_text_sim)):
                prev["end_ms"] = max(prev_e, item_e)
                if len(item_zh) > len(prev_zh):
                    prev["zh_text"] = item_zh
                if not prev.get("voice_override") and item.get("voice_override"):
                    prev["voice_override"] = item["voice_override"]
                if not prev.get("bbox_json") and item.get("bbox_json"):
                    prev["bbox_json"] = item["bbox_json"]
                matched = True
                break
            elif time_overlap_ratio > 0.85:
                if len(item_zh) > len(prev_zh):
                    prev["zh_text"] = item_zh
                if not prev.get("bbox_json") and item.get("bbox_json"):
                    prev["bbox_json"] = item["bbox_json"]
                matched = True
                break

        if not matched:
            all_segments.append(item)

    @classmethod
    def stream_ocr_long_video(
        cls,
        video_path: str,
        work_dir: str,
        scanner,
        fps: int = 2,
        crop_ratio: float = 0.28,
        crop_y_offset: float = None,
        progress_cb: Callable[[int, str], None] = None,
    ) -> List[Dict]:
        """
        ស្កេនអក្សរចិនលើវីដេអូវែង ៥ ម៉ោង ដោយទាញរូបភាពម្តង ១០ នាទី (Overlap 15s) រួចលុបចោលភ្លាមៗ
        """
        safe_video = cls._win_safe_path(video_path)
        total_sec = cls.get_duration_sec(video_path)
        tmp_frames = Path(work_dir) / "_stream_frames"
        tmp_frames.mkdir(parents=True, exist_ok=True)
        all_segments: List[Dict] = []

        crop_ratio = max(0.08, min(0.60, float(crop_ratio)))
        if crop_y_offset is None:
            crop_y_offset = 1.0 - crop_ratio
        crop_y_offset = max(0.0, min(1.0 - crop_ratio, float(crop_y_offset)))

        start_sec = 0.0
        step_sec = max(60.0, float(cls.CHUNK_SECONDS - cls.OVERLAP_SEC))

        while start_sec < total_sec - 0.2:
            dur = min(float(cls.CHUNK_SECONDS), total_sec - start_sec)
            if dur <= 0.2:
                break
            offset_ms = int(round(start_sec * 1000))

            for f in tmp_frames.glob("*.jpg"):
                f.unlink(missing_ok=True)

            vf = f"fps={fps},crop=iw:ih*{crop_ratio:.3f}:0:ih*{crop_y_offset:.3f},eq=contrast=1.25:brightness=0.02"
            hw = get_hardware_profile()
            ff_threads = str(min(2, hw["ffmpeg_threads"]))
            res = subprocess.run(
                [
                    "ffmpeg", "-y", "-threads", ff_threads, "-err_detect", "ignore_err",
                    "-ss", f"{start_sec:.3f}", "-t", f"{dur:.3f}",
                    "-i", safe_video, "-vf", vf, "-q:v", "3",
                    str(tmp_frames / "frame_%06d.jpg")
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=hw["creationflags"],
            )
            if res.returncode != 0 and not list(tmp_frames.glob("*.jpg")):
                break

            try:
                chunk_items = scanner.scan_frames(
                    str(tmp_frames), fps=fps, crop_y_offset=crop_y_offset, crop_ratio=crop_ratio
                )
            except TypeError:
                chunk_items = scanner.scan_frames(str(tmp_frames), fps=fps)
            for item in chunk_items:
                item["start_ms"] += offset_ms
                item["end_ms"] += offset_ms
                sim_fn = getattr(scanner, "_similar", None)
                cls._merge_or_append_segment(all_segments, item, similarity_fn=sim_fn)

            gc.collect()
            if progress_cb:
                pct = min(99, int((min(start_sec + dur, total_sec) / max(1.0, total_sec)) * 100))
                progress_cb(
                    pct,
                    f"ស្កេន OCR បាន {int(min(start_sec + dur, total_sec)//60)} / {int(max(1, total_sec//60))} នាទី ({pct}%)..."
                )

            if start_sec + cls.CHUNK_SECONDS >= total_sec:
                break
            start_sec += step_sec

        for f in tmp_frames.glob("*.jpg"):
            f.unlink(missing_ok=True)

        split_items = split_all_segments(all_segments, max_chars=12, max_duration_ms=3800)
        return cls.enforce_monotonic_slots(split_items, gap_ms=25)

    @classmethod
    def stream_voice_long_video(
        cls,
        video_path: str,
        work_dir: str,
        transcriber,
        mode: str,
        api_cfg: dict,
        progress_cb: Callable[[int, str], None] = None,
    ) -> List[Dict]:
        """
        ស្តាប់សំឡេងលើវីដេអូវែង ៥ ម៉ោង ម្តង ១០ នាទី (Overlap 15s) ការពារកុំឲ្យអស់ RAM និងការពារ Error 4294967294
        """
        if not cls.has_audio_stream(video_path):
            raise RuntimeError(
                "វីដេអូនេះមិនមានសំឡេង (No Audio Track) ទេ! សូមប្តូរទៅប្រើ 'ស្កេនអក្សរពីរូបភាព (OCR)' ជំនួសវិញ។"
            )

        safe_video = cls._win_safe_path(video_path)
        total_sec = cls.get_duration_sec(video_path)
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        tmp_wav = str(Path(work_dir) / "_stream_chunk.wav")
        all_segments: List[Dict] = []

        start_sec = 0.0
        step_sec = max(60.0, float(cls.CHUNK_SECONDS - cls.OVERLAP_SEC))

        while start_sec < total_sec - 0.25:
            remaining = total_sec - start_sec
            if remaining <= 0.25:
                break

            dur = min(float(cls.CHUNK_SECONDS), remaining)
            offset_ms = int(round(start_sec * 1000))
            Path(tmp_wav).unlink(missing_ok=True)

            # ប្រើ -err_detect ignore_err និង -ss ក្រោយ -i + -map 0:a:0 ដើម្បីការពារ Error 4294967294 លើវីដេអូ TikTok/Douyin
            hw = get_hardware_profile()
            ff_threads = str(min(2, hw["ffmpeg_threads"]))
            cmd = [
                "ffmpeg", "-y", "-threads", ff_threads, "-err_detect", "ignore_err",
                "-i", safe_video,
                "-ss", f"{start_sec:.3f}", "-t", f"{dur:.3f}",
                "-map", "0:a:0", "-vn",
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                tmp_wav
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=hw["creationflags"])

            # បើកំណាត់ចុងក្រោយខូច Frame ឬគ្មានទិន្នន័យសំឡេង -> បញ្ចប់ Loop ដោយសុវត្ថិភាព (មិនបោះ Error ក្រហម)
            if res.returncode != 0 or not Path(tmp_wav).exists() or Path(tmp_wav).stat().st_size < 1024:
                if start_sec == 0.0:
                    err_msg = res.stderr.decode("utf-8", errors="ignore")[-300:]
                    raise RuntimeError(f"FFmpeg មិនអាចទាញសំឡេងពីវីដេអូនេះបានទេ៖\n{err_msg}")
                break

            if mode == "local":
                items = transcriber.transcribe_local(tmp_wav, model_size=api_cfg.get("whisper_model", "base"))
            else:
                items = transcriber.transcribe_api(
                    tmp_wav, api_cfg["api_key"], api_cfg["base_url"], api_cfg.get("asr_model", "whisper-1")
                )

            for item in items:
                item["start_ms"] += offset_ms
                item["end_ms"] += offset_ms
                cls._merge_or_append_segment(all_segments, item)

            gc.collect()
            if progress_cb:
                pct = min(99, int((min(start_sec + dur, total_sec) / max(1.0, total_sec)) * 100))
                progress_cb(
                    pct,
                    f"ស្តាប់សំឡេងបាន {int(min(start_sec + dur, total_sec)//60)} / {int(max(1, total_sec//60))} នាទី ({pct}%)..."
                )

            if start_sec + cls.CHUNK_SECONDS >= total_sec:
                break
            start_sec += step_sec

        Path(tmp_wav).unlink(missing_ok=True)
        split_items = split_all_segments(all_segments, max_chars=12, max_duration_ms=3800)
        return cls.enforce_monotonic_slots(split_items, gap_ms=25)

    # =========================================================================
    # FEATURE 1 (BATCH 2): AI VIRAL SHORTS CLIPPER (9:16 AUTO-CUT 10-20 CLIPS)
    # =========================================================================
    @classmethod
    def detect_viral_short_scenes(
        cls,
        segments: List[Dict],
        total_dur_ms: int,
        translator=None,
        max_clips: int = 15,
        min_sec: int = 45,
        max_sec: int = 90,
    ) -> List[Dict]:
        """
        Analyzes the translated Khmer script of a long movie/drama (1–5 hours) using Gemini/OpenAI
        (with deterministic dramatic-cliffhanger scoring fallback) to select the top 10–20 most
        dramatic 45s–90s cliffhanger scenes ready for TikTok / Facebook Reels / YouTube Shorts.
        """
        import re
        total_dur_ms = max(3000, int(total_dur_ms or 60000))
        max_clips = max(1, min(20, int(max_clips or 15)))
        min_ms = max(2000, min(int(min_sec) * 1000, max(2000, total_dur_ms // 2)))
        max_ms = max(min_ms + 1000, min(int(max_sec) * 1000, total_dur_ms))

        # 1. Build candidate 60s storyboard windows across the timeline so even 5-hour scripts fit cleanly in LLM context
        segs = sorted(segments or [], key=lambda s: int(s.get("start_ms", 0)))
        if not segs:
            # No script available -> evenly space highlights
            step = max(min_ms, total_dur_ms // max(1, min(max_clips, max(1, total_dur_ms // max(1, min_ms)))))
            out = []
            cur = 0
            idx = 1
            while cur < total_dur_ms - 1500 and len(out) < max_clips:
                end = min(total_dur_ms, cur + max_ms)
                out.append({
                    "start_ms": cur,
                    "end_ms": end,
                    "hook_title": f"ឈុតពិសេសទី{idx}",
                    "score": 1.0,
                })
                cur += step
                idx += 1
            return out

        # Score candidate windows by dramatic density & emotional intensity
        drama_kws = (
            "!", "?", "ស្អី", "ក្បត់", "កុហក", "ការពិត", "សម្លាប់", "ភ្ញាក់ផ្អើល", "ស្មានមិនដល់",
            "យំ", "ឈឺចាប់", "ស្រឡាញ់", "សោកស្តាយ", "ប្រយ័ត្ន", "ឈប់", "ហ៊ាន", "ងាប់",
            "不可能", "真相", "背叛", "杀", "救命", "骗", "滚", "对不起", "哭",
        )

        # Group segments into ~45s-75s story beats
        beats = []
        target_win = min(max_ms, max(min_ms, 62000))
        i = 0
        n = len(segs)
        while i < n:
            b_start = int(segs[i].get("start_ms", 0))
            b_end = int(segs[i].get("end_ms", b_start + 1500))
            texts = []
            score = 0.0
            j = i
            while j < n:
                s_ms = int(segs[j].get("start_ms", 0))
                e_ms = int(segs[j].get("end_ms", s_ms + 1000))
                if (e_ms - b_start) > max_ms and (b_end - b_start) >= min_ms:
                    break
                b_end = max(b_end, e_ms)
                txt = (segs[j].get("kh_text") or segs[j].get("zh_text") or "").strip()
                if txt:
                    texts.append(txt)
                    kw_hits = sum(1 for kw in drama_kws if kw in txt)
                    score += 1.0 + kw_hits * 2.5
                j += 1
                if (b_end - b_start) >= target_win:
                    break

            dur_b = max(1000, b_end - b_start)
            if dur_b < min_ms:
                b_end = min(total_dur_ms, b_start + min_ms)
            # Slightly pad edges for clean dramatic breathing room
            pad_s = max(0, b_start - 300)
            pad_e = min(total_dur_ms, b_end + 400)
            summary = " ".join(texts[:6])[:240]
            best_line = max(texts, key=lambda t: sum(2 for kw in drama_kws if kw in t) + min(len(t), 50)) if texts else "ឈុតពិសេស"
            beats.append({
                "idx": len(beats),
                "start_ms": pad_s,
                "end_ms": pad_e,
                "score": round(score / max(1.0, (pad_e - pad_s) / 10000.0), 2),
                "summary": summary,
                "hook_title": best_line[:52].strip(),
            })
            i = max(i + 1, j)

        # 2. Ask Gemini/OpenAI to rank & title the top dramatic cliffhanger scenes when LLM is configured
        if translator is not None and hasattr(translator, "_call_llm_json") and len(beats) >= 1:
            # Send top ~45 highest-energy beats across the whole movie so 1-5h movies fit cleanly
            cand_beats = sorted(beats, key=lambda b: b["score"], reverse=True)[:45]
            cand_beats.sort(key=lambda b: b["start_ms"])
            compact = [
                {
                    "idx": b["idx"],
                    "start_sec": round(b["start_ms"] / 1000.0, 1),
                    "end_sec": round(b["end_ms"] / 1000.0, 1),
                    "dialogue": b["summary"][:160],
                }
                for b in cand_beats
            ]
            want_n = min(max_clips, len(compact))
            prompt = (
                f"You are an elite viral TikTok/Reels movie editor. From the drama scenes below, select the top {want_n} "
                f"MOST dramatic cliffhanger scenes (each {min_sec}s–{max_sec}s) with maximum viewer retention.\n"
                "Return ONLY a JSON array of objects: "
                '[{"idx": <int>, "start_sec": <float>, "end_sec": <float>, "hook_title": "<short punchy Khmer title max 45 chars>"}]\n'
                "Use pure Khmer for hook_title (ZERO Chinese). Order from most viral to least.\n"
                f"Scenes:\n{compact}"
            )
            parsed = translator._call_llm_json(prompt, temperature=0.45, max_tokens=1600)
            if isinstance(parsed, list) and parsed:
                llm_scenes = []
                used_ranges = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    s_ms = int(round(float(item.get("start_sec", 0)) * 1000))
                    e_ms = int(round(float(item.get("end_sec", 0)) * 1000))
                    if e_ms <= s_ms + 1500:
                        b_match = next((b for b in beats if b["idx"] == item.get("idx")), None)
                        if b_match:
                            s_ms, e_ms = b_match["start_ms"], b_match["end_ms"]
                        else:
                            continue
                    s_ms = max(0, min(total_dur_ms - 1500, s_ms))
                    e_ms = max(s_ms + 1500, min(total_dur_ms, e_ms))
                    if (e_ms - s_ms) > max_ms:
                        e_ms = s_ms + max_ms
                    # Skip overlapping duplicates
                    if any(min(e_ms, ue) - max(s_ms, us) > 5000 for us, ue in used_ranges):
                        continue
                    raw_hk = str(item.get("hook_title") or "").strip()
                    clean_hk = re.sub(r"[\u4e00-\u9fff\u3400-\u4dbf]", "", raw_hk).strip() or f"ឈុតក្តៅ_{len(llm_scenes)+1:02d}"
                    llm_scenes.append({
                        "start_ms": s_ms,
                        "end_ms": e_ms,
                        "hook_title": clean_hk[:55],
                    })
                    used_ranges.append((s_ms, e_ms))
                    if len(llm_scenes) >= max_clips:
                        break
                if llm_scenes:
                    return llm_scenes

        # 3. Deterministic Top-Scoring Non-Overlapping Cliffhanger Fallback
        ranked = sorted(beats, key=lambda b: b["score"], reverse=True)
        selected = []
        used = []
        for b in ranked:
            s_ms, e_ms = b["start_ms"], b["end_ms"]
            if any(min(e_ms, ue) - max(s_ms, us) > 4000 for us, ue in used):
                continue
            clean_hk = re.sub(r"[\u4e00-\u9fff\u3400-\u4dbf]", "", b["hook_title"]).strip() or f"ឈុតពិសេស_{len(selected)+1:02d}"
            selected.append({"start_ms": s_ms, "end_ms": e_ms, "hook_title": clean_hk[:50]})
            used.append((s_ms, e_ms))
            if len(selected) >= max_clips:
                break
        selected.sort(key=lambda x: x["start_ms"])
        return selected

    @classmethod
    def cut_viral_shorts(
        cls,
        video_path: str,
        segments: List[Dict],
        output_dir: str,
        edits: Dict = None,
        translator=None,
        max_clips: int = 15,
        min_sec: int = 45,
        max_sec: int = 90,
        bgm_volume: float = 0.0,
        sfx_events: List[Dict] = None,
        cancel_event=None,
        progress_cb: Callable[[int, str], None] = None,
    ) -> List[str]:
        """
        Extracts the top 10–20 cliffhanger scenes from a long movie/drama into vertical 9:16
        center-subject framed TikTok/Reels shorts with burned Khmer subtitles and ready-to-post
        filenames (`Short_01_HookTitle.mp4`).
        """
        import re
        import shutil
        from core.media_engine import MediaEngine

        if not video_path or not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        out_d = Path(output_dir)
        out_d.mkdir(parents=True, exist_ok=True)
        work_dir = out_d / "_shorts_tmp"
        work_dir.mkdir(parents=True, exist_ok=True)

        total_dur_ms = MediaEngine.get_duration_ms(video_path)
        if progress_cb:
            progress_cb(5, "⚡ AI កំពុងវិភាគសាច់រឿងស្វែងរកឈុត Cliffhanger ល្អបំផុត (45s–90s)...")

        scenes = cls.detect_viral_short_scenes(
            segments=segments,
            total_dur_ms=total_dur_ms,
            translator=translator,
            max_clips=max_clips,
            min_sec=min_sec,
            max_sec=max_sec,
        )
        if not scenes:
            raise RuntimeError("មិនអាចរកឃើញឈុតសម្រាប់កាត់ Viral Shorts បានទេ!")

        exported: List[str] = []
        total_n = len(scenes)
        base_edits = dict(edits or {})

        for idx, sc in enumerate(scenes, start=1):
            if cancel_event is not None and cancel_event.is_set():
                break
            s_ms = int(sc["start_ms"])
            e_ms = int(sc["end_ms"])
            hook_title = str(sc.get("hook_title") or f"Clip_{idx:02d}").strip()

            # Build clean ready-to-post filename: Short_01_HookTitle.mp4
            slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", hook_title)
            slug = re.sub(r"\s+", "_", slug).strip("._-")[:38] or f"ViralScene_{idx:02d}"
            out_file = str(out_d / f"Short_{idx:02d}_{slug}.mp4")

            # Slice segments & SFX relative to clip start
            clip_segs = []
            for seg in (segments or []):
                ss = int(seg.get("start_ms", 0))
                se = int(seg.get("end_ms", 0))
                if ss < e_ms and se > s_ms:
                    sc_copy = dict(seg)
                    sc_copy["start_ms"] = max(0, ss - s_ms)
                    sc_copy["end_ms"] = max(120, min(e_ms, se) - s_ms)
                    clip_segs.append(sc_copy)

            clip_sfx = []
            for sx in (sfx_events or []):
                sx_s = int(sx.get("start_ms", 0))
                if s_ms <= sx_s < e_ms:
                    sx_c = dict(sx)
                    sx_c["start_ms"] = max(0, sx_s - s_ms)
                    clip_sfx.append(sx_c)

            # Fast trim source segment
            tmp_clip = str(work_dir / f"_raw_short_{idx:02d}.mp4")
            trim_cmd = [
                "ffmpeg", "-y",
                "-ss", f"{s_ms / 1000.0:.3f}",
                "-to", f"{e_ms / 1000.0:.3f}",
                "-i", video_path,
                "-c:v", "copy", "-c:a", "copy",
                tmp_clip,
            ]
            try:
                MediaEngine.run_ffmpeg_safe(trim_cmd, fallback_cpu=False, cancel_event=cancel_event)
            except Exception:
                hw = get_hardware_profile()
                trim_cmd = [
                    "ffmpeg", "-y", "-threads", str(hw["ffmpeg_threads"]),
                    "-ss", f"{s_ms / 1000.0:.3f}",
                    "-to", f"{e_ms / 1000.0:.3f}",
                    "-i", video_path,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                    "-c:a", "aac", "-max_muxing_queue_size", "1024",
                    tmp_clip,
                ]
                MediaEngine.run_ffmpeg_safe(trim_cmd, fallback_cpu=False, cancel_event=cancel_event)

            # Configure 9:16 vertical framing + burned Khmer subtitles + hook banner
            short_edits = dict(base_edits)
            short_edits["aspect_ratio"] = "9:16"
            short_edits["burn_subs"] = 1
            short_edits["trim_start_ms"] = 0
            short_edits["trim_end_ms"] = 0
            if not (short_edits.get("hook_text") or "").strip():
                short_edits["hook_text"] = hook_title
            if "hook_enabled" not in base_edits:
                short_edits["hook_enabled"] = 1

            base_p = 10 + int(((idx - 1) / max(1, total_n)) * 85)
            span_p = max(1, int(85 / max(1, total_n)))

            def _emit_short(p_val, p_msg, bp=base_p, sp=span_p, i_num=idx):
                if progress_cb:
                    progress_cb(min(99, bp + int((p_val / 100.0) * sp)), f"[Short {i_num}/{total_n}] {p_msg}")

            try:
                MediaEngine.render_final_video(
                    video_path=tmp_clip,
                    segments=clip_segs,
                    output_mp4=out_file,
                    bgm_volume=bgm_volume,
                    edits=short_edits,
                    sfx_events=clip_sfx,
                    resolution="1080p",
                    quality_preset="balanced",
                    cancel_event=cancel_event,
                    progress_cb=_emit_short,
                )
                exported.append(out_file)
            finally:
                Path(tmp_clip).unlink(missing_ok=True)
                gc.collect()

        shutil.rmtree(work_dir, ignore_errors=True)
        if progress_cb:
            progress_cb(100, f"⚡ កាត់ Viral Shorts (9:16) បានជោគជ័យចំនួន {len(exported)} ឈុត!")
        return exported
