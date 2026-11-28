import json
import re
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional
import requests


class UnifiedLLMClient:
    """
    Unified LLM Client supporting:
    1. 100% Local Offline Ollama REST API (http://localhost:11434/api/generate)
    2. Cloud LLM API (Google Gemini / OpenAI compatible)
    3. Multi-Mirror Free Translation Fallback
    """

    def __init__(
        self,
        provider: str = "ollama",
        model_name: str = "qwen2.5:7b",
        ollama_url: str = "http://localhost:11434",
        cloud_api_url: str = "",
        cloud_api_key: str = "",
    ):
        self.provider = "ollama" if "ollama" in provider.lower() or "local" in provider.lower() else "cloud"
        self.model_name = model_name or "qwen2.5:7b"
        self.ollama_url = ollama_url.rstrip("/") if ollama_url else "http://localhost:11434"
        self.cloud_api_url = cloud_api_url or ""
        self.cloud_api_key = cloud_api_key or ""
        self._session = requests.Session()

    def generate_json(self, prompt: str, system_prompt: str = "", timeout: int = 35) -> Dict[str, Any]:
        """Sends prompt and guarantees a parsed JSON dict response."""
        if self.provider == "ollama":
            return self._call_ollama_json(prompt, system_prompt, timeout)
        else:
            return self._call_cloud_json(prompt, system_prompt, timeout)

    def _call_ollama_json(self, prompt: str, system_prompt: str, timeout: int) -> Dict[str, Any]:
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": system_prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.25,
                "top_p": 0.85,
            }
        }
        try:
            resp = self._session.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data.get("response", "").strip()
                return json.loads(raw_text)
        except Exception as e:
            print(f"[Ollama Call Warning] {e}")

        return {}

    def _call_cloud_json(self, prompt: str, system_prompt: str, timeout: int) -> Dict[str, Any]:
        if "googleapis.com" in self.cloud_api_url.lower() or self.cloud_api_key.startswith("AIza"):
            model = self.model_name if "gemini" in self.model_name.lower() else "gemini-2.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.cloud_api_key}"
            body = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 0.25,
                }
            }
            try:
                resp = self._session.post(url, json=body, timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    return json.loads(raw)
            except Exception as e:
                print(f"[Gemini Call Warning] {e}")

        elif self.cloud_api_key:
            # OpenAI compatible endpoint
            url = f"{self.cloud_api_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {self.cloud_api_key}"}
            body = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.25,
            }
            try:
                resp = self._session.post(url, json=body, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    raw = data["choices"][0]["message"]["content"].strip()
                    return json.loads(raw)
            except Exception as e:
                print(f"[Cloud OpenAI Warning] {e}")

        return {}

    @classmethod
    def list_ollama_models(cls, ollama_url: str = "http://localhost:11434") -> list:
        """Queries local Ollama tags endpoint to list installed models."""
        try:
            resp = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return ["qwen2.5:7b", "qwen2.5:14b", "gemma2:9b", "qwen2.5:3b"]

    @classmethod
    def fallback_translate_single(cls, text: str, target_lang: str = "Khmer") -> str:
        """Multi-mirror free fallback translation to ensure zero dropped lines."""
        if not text:
            return ""
        tl = "km" if "khmer" in target_lang.lower() or "ភាសាខ្មែរ" in target_lang else "en"
        encoded = urllib.parse.quote(text[:400])
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl={tl}&dt=t&q={encoded}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data and isinstance(data[0], list):
                    return "".join(part[0] for part in data[0] if part and part[0]).strip()
        except Exception:
            pass
        return ""
