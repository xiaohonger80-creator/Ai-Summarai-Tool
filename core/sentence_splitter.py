import re
from typing import List, Dict, Any

# សញ្ញាខណ្ឌប្រយោគធំៗក្នុងភាសាចិន (Major sentence terminators)
MAJOR_TERMINATORS = re.compile(r"([。！？；!?;\n]+)")

# សញ្ញាកាត់ឃ្លាក្នុងភាសាចិន (Minor clause separators / pauses)
CLAUSE_SEPARATORS = re.compile(r"([，,、…—:：]+)")

# ឈ្នាប់ភាសាចិនធម្មជាតិសម្រាប់កាត់ប្រយោគវែងដែលគ្មានសញ្ញាក្បៀស (Natural Chinese conjunctions)
CONJUNCTION_SPLITTERS = (
    "但是", "不过", "所以", "然后", "因为", "而且", "如果",
    "其实", "虽然", "或者是", "或者", "只要", "哪怕", "另外"
)

# ពាក្យដែលជាសំរាម ឬ Hallucination របស់ Whisper/OCR
JUNK_PATTERNS = [
    re.compile(r"^(谢谢观看|謝謝觀看|请订阅|請訂閱|欢迎订阅|關注我|关注我|点赞|點贊|字幕由.*制作|Subtitle by.*)$", re.IGNORECASE),
    re.compile(r"^(好的){4,}$"),
    re.compile(r"^(嗯+){3,}$"),
    re.compile(r"^[·_\-=\+~`\^@#\$%\*\/\\\|]+$"),
]


def clean_chinese_text(text: str) -> str:
    """សម្អាតចន្លោះទំនេរ និមិត្តសញ្ញាមិនប្រក្រតី និងសញ្ញាក្បៀសនៅក្បាល/កន្ទុយ"""
    if not text:
        return ""
    t = text.strip()
    # លុបចន្លោះទទេរវាងតួអក្សរចិន
    t = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", t)
    # បង្រួមចន្លោះទទេច្រើនជាន់
    t = re.sub(r"\s+", " ", t)
    # លុបសញ្ញាក្បៀស/ចុចនៅក្បាល និងចុងប្រយោគ
    t = re.sub(r"^[，,。！？!?；;、…\s]+", "", t)
    t = re.sub(r"[，,；;、\s]+$", "", t)
    return t.strip()


def is_junk_text(text: str) -> bool:
    """ពិនិត្យមើលថាតើជាអក្សរសំរាម ឬ Hallucination ឬទេ"""
    cleaned = clean_chinese_text(text)
    if not cleaned or len(cleaned) < 1:
        return True
    for pat in JUNK_PATTERNS:
        if pat.search(cleaned):
            return True
    return False


def split_chinese_text(text: str, max_chars: int = 12) -> List[str]:
    """
    កាត់បំបែកឃ្លាចិនវែងៗឲ្យទៅជាប្រយោគខ្លីៗសមរម្យ (Short natural dialogue lines)៖
    ១. កាត់តាមសញ្ញាធំ (。 ！？ ；)
    ២. ប្រសិនបើនៅតែវែង (> max_chars) -> កាត់តាមសញ្ញាក្បៀស (， 、 …)
    ៣. ប្រសិនបើនៅតែវែងគ្មានសញ្ញាក្បៀស -> កាត់តាមឈ្នាប់ (但是, 所以, 然后...)
    """
    cleaned = clean_chinese_text(text)
    if not cleaned:
        return []

    # ១. កាត់តាមសញ្ញាខណ្ឌធំៗជាមុនសិន
    major_parts = []
    tokens = MAJOR_TERMINATORS.split(cleaned)
    buffer = ""
    for token in tokens:
        if not token:
            continue
        if MAJOR_TERMINATORS.match(token):
            if buffer:
                major_parts.append(buffer + token)
                buffer = ""
            elif major_parts:
                major_parts[-1] += token
        else:
            buffer += token
    if buffer:
        major_parts.append(buffer)

    if not major_parts:
        major_parts = [cleaned]

    # ២. ពិនិត្យឃ្លានីមួយៗ បើលើស max_chars -> កាត់តាមសញ្ញាក្បៀស (， 、 …)
    final_parts = []
    for part in major_parts:
        p_clean = clean_chinese_text(part)
        if not p_clean:
            continue

        if len(p_clean) <= max_chars:
            final_parts.append(p_clean)
            continue

        # កាត់តាមសញ្ញាក្បៀស
        sub_tokens = CLAUSE_SEPARATORS.split(p_clean)
        sub_buf = ""
        for stok in sub_tokens:
            if not stok:
                continue
            if CLAUSE_SEPARATORS.match(stok):
                if sub_buf:
                    # ប្រសិនបើ sub_buf ខ្លីពេក (< 3 អក្សរ) ទុកភ្ជាប់ជាមួយឃ្លាបន្ទាប់
                    if len(sub_buf) < 3:
                        sub_buf += stok
                    else:
                        final_parts.append(clean_chinese_text(sub_buf))
                        sub_buf = ""
            else:
                if sub_buf:
                    sub_buf += stok
                else:
                    sub_buf = stok

                # បើឃ្លាក្នុង buffer វែងល្មម -> បំបែកចេញភ្លាម
                if len(sub_buf) >= max_chars:
                    final_parts.append(clean_chinese_text(sub_buf))
                    sub_buf = ""

        if sub_buf:
            c = clean_chinese_text(sub_buf)
            if c:
                final_parts.append(c)

    # ៣. ពិនិត្យមើលបើមានឃ្លាណានៅតែវែងខ្លាំង (> max_chars + 3) ហើយគ្មានសញ្ញាក្បៀស
    refined = []
    for item in final_parts:
        item = clean_chinese_text(item)
        if not item or is_junk_text(item):
            continue

        if len(item) > max_chars + 3:
            # សាកល្បងកាត់តាមឈ្នាប់ភាសាចិន
            split_done = False
            for conj in CONJUNCTION_SPLITTERS:
                idx = item.find(conj)
                # កាត់នៅពេលដែលឈ្នាប់នៅចន្លោះកណ្តាល (មិននៅក្បាល ឬកន្ទុយពេក)
                if 3 <= idx <= len(item) - 3:
                    p1 = clean_chinese_text(item[:idx])
                    p2 = clean_chinese_text(item[idx:])
                    if p1 and p2:
                        refined.append(p1)
                        refined.append(p2)
                        split_done = True
                        break
            if not split_done:
                # បើគ្មានឈ្នាប់ កាត់ចំកណ្តាលតាមចំនួនតួអក្សរ
                mid = len(item) // 2
                refined.append(clean_chinese_text(item[:mid]))
                refined.append(clean_chinese_text(item[mid:]))
        else:
            refined.append(item)

    # លុបឃ្លាទទេ ឬស្ទួនជាប់គ្នា
    res = []
    for r in refined:
        r = clean_chinese_text(r)
        if r and (not res or res[-1] != r):
            res.append(r)
    return res


def split_segment_with_words(seg: Dict[str, Any], max_chars: int = 12, max_duration_ms: int = 3800) -> List[Dict[str, Any]]:
    """
    កាត់បំបែក Segment ដោយប្រើប្រាស់ Word Timestamps ពី Faster-Whisper
    ធានាថាម៉ោងចាប់ផ្តើម និងបញ្ចប់នៃឃ្លានីមួយៗមានភាពសុក្រឹត 100% តាមសំឡេងតួអង្គនិយាយ
    """
    words = seg.get("words") or []
    zh_text = clean_chinese_text(seg.get("zh_text", ""))
    start_ms = int(seg.get("start_ms", 0))
    end_ms = int(seg.get("end_ms", start_ms + 1000))
    duration_ms = end_ms - start_ms

    if not zh_text or is_junk_text(zh_text):
        return []

    # បើឃ្លាខ្លីស្រាប់ មិនបាច់កាត់
    if len(zh_text) <= max_chars and duration_ms <= max_duration_ms and not MAJOR_TERMINATORS.search(zh_text):
        return [{
            "start_ms": start_ms,
            "end_ms": end_ms,
            "zh_text": zh_text,
            "voice_override": seg.get("voice_override", ""),
            "bbox_json": seg.get("bbox_json", ""),
        }]

    if not words:
        # បើគ្មាន Word Timestamps -> ប្រើការបែងចែកសមាមាត្រ Proportional Allocation
        return split_segment_proportional(seg, max_chars, max_duration_ms)

    # ប្រមូលផ្តុំពាក្យជាឃ្លាៗតាមសញ្ញាខណ្ឌ
    sub_clauses = []
    cur_words = []

    for w in words:
        w_text = getattr(w, "word", "") if hasattr(w, "word") else str(w.get("word", ""))
        cur_words.append(w)
        # ពិនិត្យមើលថាតើពាក្យនេះមានសញ្ញាកាត់ឃ្លាដែរឬទេ
        has_major = bool(MAJOR_TERMINATORS.search(w_text))
        has_minor = bool(CLAUSE_SEPARATORS.search(w_text))
        cur_text_len = sum(len(getattr(x, "word", "") if hasattr(x, "word") else str(x.get("word", ""))) for x in cur_words)

        if has_major or (has_minor and (cur_text_len >= max_chars or len(cur_words) >= 4)):
            sub_clauses.append(cur_words)
            cur_words = []

    if cur_words:
        if sub_clauses and len(cur_words) <= 2:
            # បើពាក្យសល់ចុងក្រោយខ្លីពេក (1-2 ពាក្យ) បញ្ចូលជាមួយឃ្លាមុន
            sub_clauses[-1].extend(cur_words)
        else:
            sub_clauses.append(cur_words)

    if not sub_clauses:
        return [seg]

    results = []
    for clause in sub_clauses:
        first_w = clause[0]
        last_w = clause[-1]

        c_start_s = getattr(first_w, "start", 0.0) if hasattr(first_w, "start") else float(first_w.get("start", 0.0))
        c_end_s = getattr(last_w, "end", 0.0) if hasattr(last_w, "end") else float(last_w.get("end", 0.0))

        c_start_ms = max(start_ms, int(round(c_start_s * 1000)))
        c_end_ms = min(end_ms, max(c_start_ms + 450, int(round(c_end_s * 1000))))

        c_text = "".join(getattr(x, "word", "") if hasattr(x, "word") else str(x.get("word", "")) for x in clause)
        c_text = clean_chinese_text(c_text)

        if c_text and not is_junk_text(c_text):
            results.append({
                "start_ms": c_start_ms,
                "end_ms": c_end_ms,
                "zh_text": c_text,
                "voice_override": seg.get("voice_override", ""),
                "bbox_json": seg.get("bbox_json", ""),
            })

    return results if results else [seg]


def split_segment_proportional(seg: Dict[str, Any], max_chars: int = 12, max_duration_ms: int = 3800) -> List[Dict[str, Any]]:
    """
    កាត់បំបែក Segment វែងៗដោយបែងចែកពេលវេលា Timecode តាមសមាមាត្រប្រវែងតួអក្សរ
    (Proportional Duration Allocation) សម្រាប់ OCR និង Cloud ASR
    """
    zh_text = clean_chinese_text(seg.get("zh_text", ""))
    start_ms = int(seg.get("start_ms", 0))
    end_ms = int(seg.get("end_ms", start_ms + 1000))
    duration_ms = max(500, end_ms - start_ms)
    voice_ov = seg.get("voice_override", "")
    bbox_j = seg.get("bbox_json", "")

    if not zh_text or is_junk_text(zh_text):
        return []

    # បើខ្លីស្រាប់ មិនបាច់កាត់
    if len(zh_text) <= max_chars and duration_ms <= max_duration_ms and not MAJOR_TERMINATORS.search(zh_text):
        return [{
            "start_ms": start_ms,
            "end_ms": end_ms,
            "zh_text": zh_text,
            "voice_override": voice_ov,
            "bbox_json": bbox_j,
        }]

    pieces = split_chinese_text(zh_text, max_chars=max_chars)
    if len(pieces) <= 1:
        return [{
            "start_ms": start_ms,
            "end_ms": end_ms,
            "zh_text": pieces[0] if pieces else zh_text,
            "voice_override": voice_ov,
            "bbox_json": bbox_j,
        }]

    total_chars = sum(max(1, len(p)) for p in pieces)
    results = []
    cur_start = start_ms

    for idx, piece in enumerate(pieces):
        char_ratio = max(1, len(piece)) / float(total_chars)
        raw_dur = int(round(duration_ms * char_ratio))
        piece_dur = max(450, raw_dur)

        p_end = cur_start + piece_dur
        # ធានាកុំឲ្យលើស end_ms ដើម (លើកលែងតែកំណាត់ចុងក្រោយ)
        if idx == len(pieces) - 1:
            p_end = max(cur_start + 450, end_ms)

        results.append({
            "start_ms": cur_start,
            "end_ms": p_end,
            "zh_text": piece,
            "voice_override": voice_ov,
            "bbox_json": bbox_j,
        })
        cur_start = p_end + 30  # ចន្លោះសុវត្ថិភាព 30ms រវាងប្រយោគ

    return results


def split_all_segments(segments: List[Dict[str, Any]], max_chars: int = 12, max_duration_ms: int = 3800) -> List[Dict[str, Any]]:
    """
    អនុវត្តការកាត់ប្រយោគវែងៗឲ្យនៅខ្លីៗលើគ្រប់ Segment ទាំងអស់
    និងតម្រៀប Timecodes ឲ្យរត់ត្រឹមត្រូវ មិនជាន់គ្នា
    """
    if not segments:
        return []

    output = []
    for s in segments:
        if s.get("words"):
            sub_segs = split_segment_with_words(s, max_chars=max_chars, max_duration_ms=max_duration_ms)
        else:
            sub_segs = split_segment_proportional(s, max_chars=max_chars, max_duration_ms=max_duration_ms)
        output.extend(sub_segs)

    if not output:
        return []

    # តម្រៀបម៉ោងឡើងវិញ និងការពារការជាន់ម៉ោង
    sorted_segs = sorted(output, key=lambda x: int(x.get("start_ms", 0)))
    final_segs = []

    for s in sorted_segs:
        s_ms = int(s.get("start_ms", 0))
        e_ms = max(s_ms + 400, int(s.get("end_ms", s_ms + 400)))
        zh = clean_chinese_text(s.get("zh_text", ""))

        if not zh or is_junk_text(zh):
            continue

        if final_segs:
            prev = final_segs[-1]
            prev_e = int(prev["end_ms"])
            if s_ms < prev_e + 20:
                s_ms = prev_e + 20
                e_ms = max(s_ms + 400, e_ms)

        s["start_ms"] = s_ms
        s["end_ms"] = e_ms
        s["zh_text"] = zh
        final_segs.append(s)

    return final_segs
