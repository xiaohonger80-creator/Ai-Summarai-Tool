import re
import threading
import time
from typing import List, Dict, Any, Optional


class APIKeyPoolManager:
    """
    ប្រព័ន្ធគ្រប់គ្រង API Key Pool ស្វ័យប្រវត្តិ (Multi-API Pool with Auto-Failover)៖
    - គាំទ្រការដាក់បញ្ចូល API Keys ច្រើន (Gemini, OpenAI, Groq, DeepSeek)
    - ពេល Key មួយអស់ Quota (429 Rate Limit / Resource Exhausted) វានឹងប្តូរ (Rotate) ទៅ Key បន្ទាប់ស្វ័យប្រវត្តិ
    - មិនឱ្យដាច់ដំណើរការបកប្រែ ឬដំណើរការស្តាប់សំឡេង (Transcribe) ឡើយ!
    """

    def __init__(self, raw_keys: str = "", cooldown_seconds: int = 600):
        self._lock = threading.RLock()
        self.cooldown_seconds = cooldown_seconds
        self.keys: List[str] = []
        self._current_index: int = 0
        self._exhausted_until: Dict[str, float] = {}  # key -> timestamp when it can be retried
        self.set_keys(raw_keys)

    def set_keys(self, raw_keys: Any):
        """បំបែក API Keys ពី String (ចុះបន្ទាត់, ក្បៀស, ឬ semicolons) ឬ List"""
        with self._lock:
            if isinstance(raw_keys, list):
                extracted = [str(k).strip() for k in raw_keys if str(k).strip()]
            elif isinstance(raw_keys, str):
                # បំបែកតាម newline, comma, semicolon
                tokens = re.split(r"[\r\n,;]+", raw_keys)
                extracted = [t.strip() for t in tokens if t.strip()]
            else:
                extracted = []

            # Remove duplicate keys while keeping order
            seen = set()
            clean_keys = []
            for k in extracted:
                if k not in seen:
                    seen.add(k)
                    clean_keys.append(k)

            self.keys = clean_keys
            if self._current_index >= len(self.keys):
                self._current_index = 0

    @property
    def total_count(self) -> int:
        with self._lock:
            return len(self.keys)

    def get_all_keys(self) -> List[str]:
        with self._lock:
            return list(self.keys)

    def get_active_key(self) -> str:
        """ទាញយក API Key សកម្មបច្ចុប្បន្ន (ប្រសិនបើ Key បច្ចុប្បន្នអស់ Quota វានឹងរំលងទៅ Key បន្ទាប់)"""
        with self._lock:
            if not self.keys:
                return ""

            now = time.time()
            n = len(self.keys)
            # ស្វែងរក Key ណាដែលមិនទាន់ជាប់ Cooldown
            for i in range(n):
                idx = (self._current_index + i) % n
                cand = self.keys[idx]
                expire_time = self._exhausted_until.get(cand, 0)
                if now >= expire_time:
                    self._current_index = idx
                    return cand

            # ប្រសិនបើជាប់ Cooldown ទាំងអស់ -> ជ្រើសរើស Key ណាដែលជិតផុត Cooldown មុនគេ
            best_key = min(self.keys, key=lambda k: self._exhausted_until.get(k, 0))
            self._current_index = self.keys.index(best_key)
            return best_key

    def get_next_round_robin_key(self) -> str:
        """
        Round-robin key distributor: cycles evenly across all healthy (non-cooldown) keys
        on each chunk/request so multi-hour batch jobs balance quota smoothly without hitting 429.
        """
        with self._lock:
            if not self.keys:
                return ""
            now = time.time()
            n = len(self.keys)
            start_idx = self._current_index
            for offset in range(n):
                idx = (start_idx + offset) % n
                cand = self.keys[idx]
                if now >= self._exhausted_until.get(cand, 0):
                    self._current_index = (idx + 1) % n
                    return cand
            best_key = min(self.keys, key=lambda k: self._exhausted_until.get(k, 0))
            self._current_index = (self.keys.index(best_key) + 1) % n
            return best_key

    def _rotate_next_key(self, failed_key: str = "", error_msg: str = "") -> Optional[str]:
        """Instant failover rotation helper when a key hits 429 Rate Limit / Quota Exceeded."""
        if failed_key:
            return self.rotate_on_failure(failed_key, error_msg)
        nxt = self.get_next_round_robin_key()
        return nxt or None

    def rotate_on_failure(self, failed_key: str, error_msg: str = "") -> Optional[str]:
        """
        កត់ត្រាថា Key នេះបានអស់ Quota ឬបរាជ័យ ហើយប្តូរទៅ Key បន្ទាប់ភ្លាមៗ។
        ត្រឡប់ Key ថ្មី ឬ None ប្រសិនបើគ្មាន Key ផ្សេងទៀត។
        """
        with self._lock:
            if not self.keys:
                return None

            now = time.time()
            # កំណត់ Cooldown រយៈពេល 10 នាទីសម្រាប់ Key ដែលអស់ Quota
            self._exhausted_until[failed_key] = now + self.cooldown_seconds

            n = len(self.keys)
            print(f"[API Pool] ⚠️ Key '...{failed_key[-6:] if len(failed_key)>6 else failed_key}' អស់ Quota ({error_msg}) -> កំពុងប្តូរទៅ Key បន្ទាប់...")

            # ស្វែងរក Key ផ្សេងទៀតក្នុង Pool
            for i in range(1, n + 1):
                idx = (self._current_index + i) % n
                cand = self.keys[idx]
                if cand != failed_key and now >= self._exhausted_until.get(cand, 0):
                    self._current_index = idx
                    print(f"[API Pool] ✅ បានប្តូរទៅ Key ថ្មីដោយស្វ័យប្រវត្តិ៖ '...{cand[-6:] if len(cand)>6 else cand}' (Key #{idx+1}/{n})")
                    return cand

            # ប្រសិនបើ Key ផ្សេងទៀតជាប់ Cooldown ដែរ ប៉ុន្តែមិនមែនជា failed_key
            other_keys = [k for k in self.keys if k != failed_key]
            if other_keys:
                cand = other_keys[0]
                self._current_index = self.keys.index(cand)
                print(f"[API Pool] 🔄 ប្រើប្រាស់ Key បម្រុង៖ '...{cand[-6:] if len(cand)>6 else cand}'")
                return cand

            return None

    def get_status_summary(self) -> Dict[str, Any]:
        """សង្ខេបស្ថានភាព API Pool សម្រាប់បង្ហាញលើ UI"""
        with self._lock:
            now = time.time()
            active_count = sum(1 for k in self.keys if now >= self._exhausted_until.get(k, 0))
            return {
                "total": len(self.keys),
                "active_available": active_count,
                "exhausted_cooldown": len(self.keys) - active_count,
                "current_index": self._current_index + 1 if self.keys else 0,
            }
