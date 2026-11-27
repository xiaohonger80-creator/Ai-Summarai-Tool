import base64
import hashlib
import hmac
import json
import os
import platform
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple, Any

_MASTER_SALT = b"AiSummarai_2026_Secure_License_Key_Gen_Salt_#99812739@KhmerDev"
LICENSE_FILE = Path("data/license.lic")
CACHE_FILE = Path("data/license_cache.dat")


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_machine_id() -> str:
    """
    Generate a deterministic, hardware-bound Machine ID for Windows PCs.
    Formats as: AS-XXXX-XXXX-XXXX
    """
    raw_guid = ""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            )
            raw_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
        except Exception:
            raw_guid = ""

    if not raw_guid:
        # Fallback to deterministic hardware traits
        node = str(uuid.getnode())
        proc = platform.processor() or platform.machine()
        node_name = platform.node()
        raw_guid = f"{node}:{proc}:{node_name}"

    digest = hashlib.sha256((raw_guid + ":AiSummaraiHwSalt2026").encode("utf-8")).hexdigest().upper()
    # Format cleanly into 3 blocks of 4 hex chars
    return f"AS-{digest[0:4]}-{digest[4:8]}-{digest[8:12]}"


def generate_license(machine_id: str, days: int, client_name: str = "") -> str:
    """
    Admin key generator:
    Creates a signed License Key valid for a specific Machine ID (or 'ALL' for universal)
    and specified number of days.
    """
    m_id = (machine_id or "ALL").strip().upper()
    now_ts = int(time.time())
    days_val = max(1, int(days))

    payload = {
        "m": m_id,
        "d": days_val,
        "t": now_ts,
        "u": (client_name or "").strip()
    }
    payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8").rstrip("=")

    sig = hmac.new(_MASTER_SALT, payload_json, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig[:16]).decode("utf-8").rstrip("=")

    return f"ASKEY-{payload_b64}.{sig_b64}"


def _verify_payload_signature(payload_b64: str, sig_b64: str) -> Optional[Dict[str, Any]]:
    try:
        pad = 4 - (len(payload_b64) % 4)
        if pad and pad < 4:
            payload_b64 += "=" * pad
        payload_bytes = base64.urlsafe_b64decode(payload_b64)

        pad_sig = 4 - (len(sig_b64) % 4)
        if pad_sig and pad_sig < 4:
            sig_b64 += "=" * pad_sig
        expected_sig = base64.urlsafe_b64decode(sig_b64)

        computed_sig = hmac.new(_MASTER_SALT, payload_bytes, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(expected_sig, computed_sig):
            return None

        data = json.loads(payload_bytes.decode("utf-8"))
        return data
    except Exception:
        return None


def verify_license(key_str: str) -> Tuple[bool, str, int, Dict[str, Any]]:
    """
    Verifies a license key:
    Returns (is_valid, message, remaining_days, payload_info)
    """
    k = (key_str or "").strip()
    if not k.startswith("ASKEY-") or "." not in k:
        return False, "ទម្រង់ License Key មិនត្រឹមត្រូវ (Invalid Key Format)", 0, {}

    raw_token = k[len("ASKEY-"):]
    parts = raw_token.split(".")
    if len(parts) != 2:
        return False, "License Key មិនត្រឹមត្រូវ (Corrupted Key)", 0, {}

    payload_b64, sig_b64 = parts[0], parts[1]
    payload = _verify_payload_signature(payload_b64, sig_b64)
    if not payload:
        return False, "License Key ក្លែងក្លាយ ឬមិនត្រឹមត្រូវ (Signature Verification Failed)", 0, {}

    curr_machine = get_machine_id()
    target_machine = payload.get("m", "")
    if target_machine != "ALL" and target_machine.upper() != curr_machine.upper():
        return False, f"License នេះមិនត្រូវជាមួយកុំព្យូទ័រនេះទេ!\n(សម្រាប់ម៉ាស៊ីន: {target_machine} | ម៉ាស៊ីនអ្នក: {curr_machine})", 0, payload

    now_ts = int(time.time())
    issued_ts = int(payload.get("t", 0))
    days = int(payload.get("d", 0))

    # Anti-Clock Rollback check
    base_dir = _get_base_dir()
    cache_path = base_dir / CACHE_FILE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    last_check_ts = 0

    if cache_path.exists():
        try:
            content = cache_path.read_text(encoding="utf-8").strip()
            parts_c = content.split(":")
            if len(parts_c) == 2:
                ts_str, h_str = parts_c
                expected_h = hashlib.sha256((ts_str + ":AntiRollbackSalt").encode("utf-8")).hexdigest()[:12]
                if h_str == expected_h:
                    last_check_ts = int(ts_str)
        except Exception:
            pass

    # If clock moved backward more than 2 hours
    if last_check_ts > 0 and now_ts < (last_check_ts - 7200):
        return False, "រកឃើញកាលបរិច្ឆេទម៉ាស៊ីនត្រូវបានកែប្រែថយក្រោយ (Clock Rollback Detected)!", 0, payload

    # Update cache with current time
    try:
        new_ts_str = str(max(now_ts, last_check_ts))
        new_h = hashlib.sha256((new_ts_str + ":AntiRollbackSalt").encode("utf-8")).hexdigest()[:12]
        cache_path.write_text(f"{new_ts_str}:{new_h}", encoding="utf-8")
    except Exception:
        pass

    # Lifetime license check (days >= 30000)
    if days >= 30000:
        return True, "License សកម្ម (Lifetime - អាយុកាលពេញ)", 99999, payload

    expire_ts = issued_ts + (days * 86400)
    if now_ts > expire_ts:
        exp_date = time.strftime("%d/%m/%Y", time.localtime(expire_ts))
        return False, f"License បានផុតកំណត់កាលពីថ្ងៃទី {exp_date}!", 0, payload

    remaining_seconds = expire_ts - now_ts
    remaining_days = max(1, int(round(remaining_seconds / 86400)))
    return True, f"License មានសុពលភាព (នៅសល់ {remaining_days} ថ្ងៃ)", remaining_days, payload


def save_license_key(key_str: str) -> bool:
    """Save the license key to disk and cache."""
    try:
        base_dir = _get_base_dir()
        lic_path = base_dir / LICENSE_FILE
        lic_path.parent.mkdir(parents=True, exist_ok=True)
        lic_path.write_text(key_str.strip(), encoding="utf-8")
        return True
    except Exception:
        return False


def load_license_key() -> str:
    """Load the saved license key from disk."""
    base_dir = _get_base_dir()
    lic_path = base_dir / LICENSE_FILE
    if lic_path.exists():
        try:
            return lic_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def get_active_license_status() -> Tuple[bool, str, int, Dict[str, Any]]:
    """Checks the currently saved license."""
    saved_key = load_license_key()
    if not saved_key:
        return False, "មិនទាន់បានបញ្ចូល License Key នៅឡើយទេ", 0, {}
    return verify_license(saved_key)
