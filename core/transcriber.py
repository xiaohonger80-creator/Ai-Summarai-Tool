import gc
import json
import os
import re
import subprocess
import time
import wave
from pathlib import Path
import numpy as np
from core.api_pool import APIKeyPoolManager
from core.sentence_splitter import split_all_segments, clean_chinese_text, is_junk_text

VALID_PROFILES = {"female", "male", "inner_thought", "phone_call"}

INNER_THOUGHT_KEYWORDS = (
    "心想", "心里", "暗道", "暗想", "心道", "想道", "自语", "自言自语",
    "嘀咕", "难道", "内心", "独白", "（", "(", "怎么会这样", "怎么可能", "原来是这样"
)

PHONE_KEYWORDS = (
    "喂", "电话", "接通", "挂断", "挂了", "手机", "听到吗", "听得到吗",
    "信号", "通话", "拨打", "发短信", "微信"
)


class SpeechTranscriber:
    _model_cache: dict = {}

    @classmethod
    def _get_whisper_model(cls, model_size: str = "base"):
        """រក្សាទុក Model ក្នុង RAM (Cache) កុំឱ្យ Reload ឡើងវិញរៀងរាល់ 10 នាទី — គ្រប់គ្រង Thread សមស្របសម្រាប់កុំព្យូទ័រ Spech តូច"""
        if model_size not in cls._model_cache:
            from faster_whisper import WhisperModel
            cpu_cores = os.cpu_count() or 4
            # បែងចែក Threads សមរម្យ (ត្រឹមតែ 2 Cores ការពារកុំឲ្យ CPU ឡើង 95%-100% លើកុំព្យូទ័រ Spech ទាប)
            threads = max(1, min(2, cpu_cores // 2 if cpu_cores >= 4 else 1))
            try:
                import torch
                has_cuda = torch.cuda.is_available()
            except Exception:
                has_cuda = False
            device = "cuda" if has_cuda else "cpu"
            compute_type = "float16" if has_cuda else "int8"
            # CPU mode ប្រើ num_workers=1 ដើម្បីសន្សំ RAM (< 600MB) និងកាត់បន្ថយ CPU Load
            num_workers = 1 if not has_cuda else 2
            cls._model_cache[model_size] = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                cpu_threads=threads,
                num_workers=num_workers,
            )
        return cls._model_cache[model_size]

    @staticmethod
    def _load_wav_float32(wav_path: str) -> np.ndarray:
        if not wav_path or not Path(wav_path).exists() or Path(wav_path).stat().st_size < 44:
            return np.zeros(0, dtype=np.float32)
        try:
            with wave.open(wav_path, "rb") as wf:
                n_frames = wf.getnframes()
                if n_frames <= 0:
                    return np.zeros(0, dtype=np.float32)
                raw_bytes = wf.readframes(n_frames)
            if not raw_bytes or len(raw_bytes) < 2:
                return np.zeros(0, dtype=np.float32)
            audio_int16 = np.frombuffer(raw_bytes[: (len(raw_bytes) // 2) * 2], dtype=np.int16)
            return audio_int16.astype(np.float32) / 32768.0
        except Exception:
            return np.zeros(0, dtype=np.float32)

    @classmethod
    def preprocess_speech_audio(cls, wav_path: str) -> str:
        """
        បង្កើនកម្រិតច្បាស់នៃសំឡេងនិយាយចិន (Vocal Clarity Boost, Dynamic Range Compression & Denoising)
        ដើម្បីឲ្យ Whisper និង Gemini អាចស្តាប់ឮសំឡេងខ្សឹប សំឡេងគិតក្នុងចិត្ត និងសំឡេងទូរស័ព្ទបាន ១០០%
        """
        src = Path(wav_path)
        enhanced_wav = src.parent / f"{src.stem}_enhanced_asr.wav"
        if enhanced_wav.exists() and enhanced_wav.stat().st_size > 1000:
            return str(enhanced_wav)

        cpu_cores = os.cpu_count() or 4
        ffmpeg_threads = str(max(1, min(2, (cpu_cores - 1) if cpu_cores > 2 else cpu_cores)))
        cmd = [
            "ffmpeg", "-y", "-threads", ffmpeg_threads, "-i", str(src),
            "-af", "highpass=f=75,lowpass=f=7800,speechnorm=e=4:r=0.0001:l=1,volume=1.25",
            "-ar", "16000", "-ac", "1",
            str(enhanced_wav)
        ]
        c_flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=c_flags)
            if enhanced_wav.exists() and enhanced_wav.stat().st_size > 1000:
                return str(enhanced_wav)
        except Exception:
            pass
        return str(src)

    @staticmethod
    def refine_speech_boundaries(wav_path: str, segments: list) -> list:
        """
        Snaps each segment's start_ms / end_ms to the exact acoustic speech onset/offset
        using a 10ms RMS energy envelope so Khmer voiceover starts the exact millisecond
        the actor opens their mouth (eliminating dead-air lip-sync lag).
        """
        if not segments or not wav_path or not Path(wav_path).exists():
            return segments
        try:
            with wave.open(wav_path, "rb") as wf:
                sr = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        except Exception:
            return segments

        if len(audio) < int(sr * 0.1):
            return segments

        frame_len = max(1, int(sr * 0.010))  # 10ms frames
        total_ms = int((len(audio) / float(sr)) * 1000)

        for seg in segments:
            s_ms = max(0, int(seg.get("start_ms", 0)))
            e_ms = min(total_ms, max(s_ms + 250, int(seg.get("end_ms", s_ms + 400))))
            s_idx = int((s_ms / 1000.0) * sr)
            e_idx = int((e_ms / 1000.0) * sr)
            clip = audio[s_idx:e_idx]
            if len(clip) < frame_len * 6:
                continue

            n_frames = len(clip) // frame_len
            frames = clip[: n_frames * frame_len].reshape(n_frames, frame_len)
            rms = np.sqrt(np.mean(frames ** 2, axis=1))
            peak_rms = float(np.max(rms)) if len(rms) else 0.0
            if peak_rms < 120.0:
                continue

            # Onset/offset threshold at 12% of segment peak RMS (min 90.0)
            thresh = max(90.0, peak_rms * 0.12)
            active = np.where(rms >= thresh)[0]
            if len(active) == 0:
                continue

            # Trim leading dead silence (keep 20ms natural breath pad; cap trim at 180ms)
            lead_frames = max(0, int(active[0]) - 2)
            lead_trim_ms = min(180, lead_frames * 10)

            # Trim trailing dead silence (keep 30ms release pad; cap trim at 160ms)
            trail_frames = max(0, (n_frames - 1 - int(active[-1])) - 3)
            trail_trim_ms = min(160, trail_frames * 10)

            new_s = s_ms + lead_trim_ms
            new_e = e_ms - trail_trim_ms
            if new_e - new_s >= 320:
                seg["start_ms"] = new_s
                seg["end_ms"] = new_e

        return segments

    @staticmethod
    def detect_character_from_wav(wav_path: str, segments: list) -> list:
        """
        វិភាគ Pitch (F0), កម្រិតថាមពលសំឡេង (RMS), Spectral Band-limit (300Hz-3400Hz) និងពាក្យគន្លឹះ
        ដើម្បីបែងចែក៖
        - ស្រី (female)
        - ប្រុស (male)
        - សំឡេងក្នុងចិត្ត (inner_thought: ខ្សឹប/រំពងក្នុងចិត្ត)
        - សំឡេងនិយាយទូរស័ព្ទ (phone_call: សំឡេងចេញពីទូរស័ព្ទ/ឧបករណ៍បំពងសំឡេង)
        """
        try:
            with wave.open(wav_path, "rb") as wf:
                sr = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        except Exception:
            return segments

        if len(audio) == 0:
            return segments

        global_rms = float(np.sqrt(np.mean(audio ** 2))) + 1e-6
        min_lag = int(sr / 300)
        max_lag = int(sr / 75)

        for seg in segments:
            zh = seg.get("zh_text") or ""

            # ១. ពិនិត្យពាក្យគន្លឹះសំឡេងក្នុងចិត្ត (Inner Thought) និងទូរស័ព្ទ (Phone Call)
            if any(k in zh for k in INNER_THOUGHT_KEYWORDS) or zh.startswith("（") or zh.startswith("("):
                seg["voice_override"] = "inner_thought"
                continue
            if any(k in zh for k in PHONE_KEYWORDS) and (zh.startswith("喂") or "电话" in zh or "手机" in zh):
                seg["voice_override"] = "phone_call"
                continue

            s_idx = max(0, int((seg["start_ms"] / 1000.0) * sr))
            e_idx = min(len(audio), int((seg["end_ms"] / 1000.0) * sr))
            if s_idx >= len(audio) or e_idx <= s_idx:
                continue
            clip = audio[s_idx:e_idx]

            if len(clip) > int(sr * 1.5):
                mid = len(clip) // 2
                half = int(sr * 0.75)
                clip = clip[mid - half : mid + half]

            if len(clip) < max_lag * 2:
                continue

            clip = clip - np.mean(clip)
            clip_rms = float(np.sqrt(np.mean(clip ** 2)))
            if clip_rms < 100:
                seg["voice_override"] = "inner_thought"
                continue

            # ពិនិត្យមើលថាតើជាសំឡេងទូរស័ព្ទ (Telephone Bandpass 350Hz-3200Hz) ឬទេ
            fft_mag = np.abs(np.fft.rfft(clip))
            freqs = np.fft.rfftfreq(len(clip), d=1.0 / sr)
            total_energy = float(np.sum(fft_mag ** 2)) + 1e-6
            tel_band = (freqs >= 350) & (freqs <= 3200)
            high_band = freqs > 3600
            tel_ratio = float(np.sum(fft_mag[tel_band] ** 2)) / total_energy
            high_ratio = float(np.sum(fft_mag[high_band] ** 2)) / total_energy

            corr = np.correlate(clip, clip, mode="full")
            corr = corr[len(corr) // 2 :]
            if max_lag >= len(corr):
                continue

            peak_lag = np.argmax(corr[min_lag:max_lag]) + min_lag
            f0 = sr / float(peak_lag)

            # ២. សំឡេងនិយាយទូរស័ព្ទ
            if (tel_ratio > 0.82 and high_ratio < 0.02) or any(k in zh for k in PHONE_KEYWORDS):
                seg["voice_override"] = "phone_call"
            # ៣. សំឡេងក្នុងចិត្ត / ខ្សឹប (< 35% នៃកម្រិតសំឡេងទូទៅ)
            elif clip_rms < global_rms * 0.35:
                seg["voice_override"] = "inner_thought"
            elif f0 > 165.0:
                seg["voice_override"] = "female"
            else:
                seg["voice_override"] = "male"

        return segments

    def transcribe_local(self, wav_path: str, model_size: str = "base"):
        if not wav_path or not Path(wav_path).exists() or Path(wav_path).stat().st_size < 44:
            return []
        clean_wav = self.preprocess_speech_audio(wav_path)
        audio_array = self._load_wav_float32(clean_wav)
        if len(audio_array) < 160 or float(np.max(np.abs(audio_array))) < 1e-4:
            if clean_wav != wav_path:
                Path(clean_wav).unlink(missing_ok=True)
            return []
        model = self._get_whisper_model(model_size)

        segments, _ = model.transcribe(
            audio_array,
            language="zh",
            beam_size=1,       # Greedy decoding (3x to 5x faster than beam_size=5)
            best_of=1,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.28,  # ចាប់សំឡេងនិយាយចំពេលតួហើបមាត់ កាត់បន្ថយ Dead-Air Delay
                min_speech_duration_ms=60,
                min_silence_duration_ms=180,
                speech_pad_ms=120,
            ),
            word_timestamps=False, # កាត់បន្ថយការគណនា Attention Matrix ដែលនាំឱ្យយឺត
            condition_on_previous_text=False,
            no_speech_threshold=0.50,
            compression_ratio_threshold=2.4,
            initial_prompt="以下是中国影视剧普通话对白、内心独白、电话交谈、悄悄话及旁白。请逐字准确转录，使用规范标点（，。！？）进行自然短句断句：",
        )

        items = []
        for seg in segments:
            text = clean_chinese_text(seg.text)
            if not text or is_junk_text(text):
                continue
            items.append({
                "start_ms": int(seg.start * 1000),
                "end_ms": max(int(seg.end * 1000), int(seg.start * 1000) + 420),
                "zh_text": text,
                "voice_override": "",
                "words": getattr(seg, "words", None),
            })

        # Free audio arrays from memory immediately on low-spec PCs
        del audio_array
        gc.collect()

        # សម្អាត temporary enhanced wav
        if clean_wav != wav_path:
            try:
                Path(clean_wav).unlink(missing_ok=True)
            except Exception:
                pass

        short_items = split_all_segments(items, max_chars=12, max_duration_ms=3800)
        refined_items = self.refine_speech_boundaries(wav_path, short_items)
        return self.detect_character_from_wav(wav_path, refined_items)

    def transcribe_api(self, wav_path: str, api_key: str, base_url: str, model: str = "whisper-1"):
        pool = APIKeyPoolManager(api_key)
        first_k = pool.get_active_key() or (api_key or "").strip()
        if "googleapis.com" in (base_url or "").lower() or (first_k and (first_k.startswith("AIza") or first_k.startswith("AQ."))):
            return self._transcribe_gemini(wav_path, api_key)

        clean_wav = self.preprocess_speech_audio(wav_path)
        from openai import OpenAI
        resp = None
        max_attempts = max(2, min(pool.total_count + 1, 8))
        last_err = None
        for att in range(max_attempts):
            curr_k = pool.get_next_round_robin_key() if (att == 0 and pool.total_count > 1) else (pool.get_active_key() or first_k)
            client = OpenAI(api_key=curr_k or "local-no-key-needed", base_url=base_url or None)
            try:
                with open(clean_wav, "rb") as f:
                    resp = client.audio.transcriptions.create(
                        model=model,
                        file=f,
                        language="zh",
                        prompt="以下是中国影视剧普通话对话、内心独白、电话声及旁白。请逐字准确转录每一句话，使用规范标点（，。！？）分成自然短句，切勿输出过长句子。",
                        response_format="verbose_json",
                    )
                break
            except Exception as ex:
                last_err = ex
                ex_s = str(ex).lower()
                if any(tok in ex_s for tok in ("429", "rate_limit", "quota", "resource_exhausted")):
                    if pool._rotate_next_key(failed_key=curr_k, error_msg=str(ex)[:100]):
                        continue
                raise

        if resp is None and last_err is not None:
            raise last_err

        if clean_wav != wav_path:
            try:
                Path(clean_wav).unlink(missing_ok=True)
            except Exception:
                pass

        items = []
        for s in getattr(resp, "segments", []):
            text = clean_chinese_text(s.get("text", ""))
            if not text or is_junk_text(text):
                continue
            items.append({
                "start_ms": int(s["start"] * 1000),
                "end_ms": max(int(s["end"] * 1000), int(s["start"] * 1000) + 420),
                "zh_text": text,
                "voice_override": "",
            })
        short_items = split_all_segments(items, max_chars=12, max_duration_ms=3800)
        refined_items = self.refine_speech_boundaries(wav_path, short_items)
        return self.detect_character_from_wav(wav_path, refined_items)

    def _transcribe_gemini(self, wav_path: str, api_key: str):
        """ប្រើ Gemini 3.1/3.8 ស្តាប់សំឡេងចិនច្បាស់លាស់ និងញែក ស្រី, ប្រុស, សំឡេងក្នុងចិត្ត និងសំឡេងទូរស័ព្ទ (គាំទ្រ Multi-API Key Failover)"""
        clean_wav = self.preprocess_speech_audio(wav_path)
        pool = APIKeyPoolManager(api_key)
        max_attempts = min(max(2, pool.total_count), 5)
        resp = None

        prompt = (
            "You are an expert Chinese audio transcriber for Asian films, dramas, and short video clips. "
            "Transcribe 100% of ALL spoken Chinese dialogue in this audio verbatim, word-for-word, with extreme accuracy. "
            "PAY SPECIAL ATTENTION TO:\n"
            "1. Fast-talking characters (accurately catch rapid speech without dropping words).\n"
            "2. Telephone conversations ('phone_call'): voices through a phone, walkie-talkie, or radio.\n"
            "3. Internal monologue ('inner_thought'): a character's thoughts, mind voiceover, reflections, or soft whispers.\n"
            "4. Normal on-screen dialogue ('female' or 'male').\n"
            "IMPORTANT: Break long speeches into short, natural dialogue lines (under 3.5 seconds or 12 Chinese characters each). "
            "Return ONLY a JSON array of objects with keys: "
            "'start_ms' (integer), 'end_ms' (integer), 'zh_text' (Simplified Chinese with punctuation), and 'voice_type' (one of: 'female', 'male', 'inner_thought', 'phone_call')."
        )

        for attempt_k in range(max_attempts):
            curr_key = pool.get_active_key()
            if not curr_key:
                break
            client = None
            uploaded = None
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=curr_key)
                uploaded = client.files.upload(file=clean_wav)
                for m_name in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-3.1-flash-lite"):
                    try:
                        resp = client.models.generate_content(
                            model=m_name,
                            contents=[uploaded, prompt],
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.05,
                            ),
                        )
                        if resp and resp.text:
                            break
                    except Exception as gen_err:
                        if "429" in str(gen_err) or "RESOURCE_EXHAUSTED" in str(gen_err) or "quota" in str(gen_err).lower():
                            pool.rotate_on_failure(curr_key, str(gen_err))
                            break
                        continue
            except Exception as up_err:
                if "429" in str(up_err) or "RESOURCE_EXHAUSTED" in str(up_err) or "quota" in str(up_err).lower():
                    pool.rotate_on_failure(curr_key, str(up_err))
                    continue
            finally:
                if client and uploaded:
                    try:
                        client.files.delete(name=uploaded.name)
                    except Exception:
                        pass

            if resp and resp.text:
                break

        if clean_wav != wav_path:
            try:
                Path(clean_wav).unlink(missing_ok=True)
            except Exception:
                pass

        if not resp or not resp.text:
            return []

        raw_txt = resp.text.strip()
        raw_txt = re.sub(r"^```json\s*|\s*```$", "", raw_txt)
        items = json.loads(raw_txt)

        results = []
        for x in items:
            text_val = str(x.get("zh_text", "")).strip()
            if not text_val:
                continue
            start_ms = int(x["start_ms"])
            end_ms = max(int(x["end_ms"]), start_ms + 420)
            vtype = str(x.get("voice_type", "female")).lower().strip()
            if vtype not in VALID_PROFILES:
                vtype = "female"
            results.append({
                "start_ms": start_ms,
                "end_ms": end_ms,
                "zh_text": clean_chinese_text(text_val),
                "voice_override": vtype,
            })
        split_items = split_all_segments(results, max_chars=12, max_duration_ms=3800)
        return self.refine_speech_boundaries(wav_path, split_items)
