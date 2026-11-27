import datetime
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

APP_VERSION = "1.5.10"
GITHUB_OWNER = "xiaohonger80-creator"
GITHUB_REPO = "Ai-Summarai-Tool"
GITHUB_BRANCH = "main"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_MANIFEST_URL = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/version.json"
GITHUB_UPDATE_ZIP_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/release_output/AiSummarai_Update.zip"
)


def main():
    print("=" * 60)
    print(f"  Sync & Package Ai Summarai v{APP_VERSION} (GitHub Update Engine)")
    print("=" * 60)

    # 1. Update core/updater.py
    upd_path = ROOT / "core" / "updater.py"
    if upd_path.exists():
        t = upd_path.read_text(encoding="utf-8")
        t = re.sub(r'APP_VERSION\s*=\s*["\'][^"\']+["\']', f'APP_VERSION = "{APP_VERSION}"', t, count=1)
        upd_path.write_text(t, encoding="utf-8")
        print(f"[OK] Updated core/updater.py to v{APP_VERSION}")

    # 2. Update updater_config.json (GitHub Official Server)
    cfg_path = ROOT / "updater_config.json"
    cfg = {
        "app_version": APP_VERSION,
        "update_provider": "github",
        "github_repo_url": GITHUB_REPO_URL,
        "github_branch": GITHUB_BRANCH,
        "manifest_url": GITHUB_MANIFEST_URL,
        "update_zip_url": GITHUB_UPDATE_ZIP_URL,
        "auto_check_updates": True,
        "last_check_timestamp": 0,
    }
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Updated updater_config.json -> GitHub ({GITHUB_OWNER}/{GITHUB_REPO})")

    # 3. Update version.json
    v_path = ROOT / "version.json"
    v_data = {
        "version": APP_VERSION,
        "app_version": APP_VERSION,
        "provider": "github",
        "release_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "repo_url": GITHUB_REPO_URL,
        "manifest_url": GITHUB_MANIFEST_URL,
        "download_url": GITHUB_UPDATE_ZIP_URL,
        "changelog": (
            "• 🐙 GitHub Auto-Updater: ប្តូរប្រព័ន្ធ Update ពី Google Drive មក GitHub ផ្លូវការ (លឿន មានស្ថេរភាព និងគ្មានដែនកំណត់ Download)។\n"
            "• 📚 Series Profile & Character Voice Memory: រក្សាទុក និងផ្ទុកសំណុំរឿងភាគ (សំឡេងតួអង្គ, Glossary, Subtitle/Mask Layout, Intro/Outro) ដោយស្វ័យប្រវត្តិគ្រប់ភាគ ១–៥០។\n"
            "• 🎼 AI Vocal Remover (Keep BGM Only) + 🖼️ AI Hook Banner & Thumbnail + 🎬 Auto Intro/Outro Stitcher + 🚀 1-Click Auto Dub & Export។\n"
            "• ⚡ AI Viral Shorts Clipper (9:16), 🎵 Auto-Place Emotion SFX & BGM, 🔑 Multi-API Round-Robin & 429 Failover, ✨ HD Clarity Upscaler 1080p និង 📲 Social Pack។"
        ),
    }
    v_path.write_text(json.dumps(v_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Updated version.json to v{APP_VERSION} (GitHub URLs)")

    # 4. Update version_info.txt
    v_info_path = ROOT / "version_info.txt"
    if v_info_path.exists():
        try:
            v_parts = [p for p in APP_VERSION.split(".") if p.isdigit()]
            while len(v_parts) < 4:
                v_parts.append("0")
            tuple_str = f"({', '.join(v_parts[:4])})"
            vt = v_info_path.read_text(encoding="utf-8")
            vt = re.sub(r'filevers=\([^)]+\)', f'filevers={tuple_str}', vt)
            vt = re.sub(r'prodvers=\([^)]+\)', f'prodvers={tuple_str}', vt)
            vt = re.sub(r"StringStruct\('FileVersion',\s*'[^']+'\)", f"StringStruct('FileVersion', '{APP_VERSION}')", vt)
            vt = re.sub(r"StringStruct\('ProductVersion',\s*'[^']+'\)", f"StringStruct('ProductVersion', '{APP_VERSION}')", vt)
            v_info_path.write_text(vt, encoding="utf-8")
            print(f"[OK] Updated version_info.txt to v{APP_VERSION}")
        except Exception as e:
            print(f"[WARN] version_info.txt: {e}")

    # 5. Update AiSummarai_Installer.iss
    iss_path = ROOT / "AiSummarai_Installer.iss"
    if iss_path.exists():
        try:
            it = iss_path.read_text(encoding="utf-8")
            it = re.sub(r'#define MyAppVersion\s+"[^"]+"', f'#define MyAppVersion "{APP_VERSION}"', it)
            iss_path.write_text(it, encoding="utf-8")
            print(f"[OK] Updated AiSummarai_Installer.iss to v{APP_VERSION}")
        except Exception as e:
            print(f"[WARN] AiSummarai_Installer.iss: {e}")

    # 6. Sync to dist/AiSummarai
    dist_dir = ROOT / "dist" / "AiSummarai"
    if dist_dir.exists():
        d_core = dist_dir / "core"
        d_core.mkdir(parents=True, exist_ok=True)
        for cf in (ROOT / "core").glob("*.py"):
            shutil.copy2(cf, d_core / cf.name)
        d_ui = dist_dir / "ui"
        d_ui.mkdir(parents=True, exist_ok=True)
        for uf in (ROOT / "ui").glob("*.py"):
            shutil.copy2(uf, d_ui / uf.name)
        shutil.copy2(v_path, dist_dir / "version.json")
        shutil.copy2(cfg_path, dist_dir / "updater_config.json")
        print("[OK] Synced updated files to dist/AiSummarai/")

    # 7. Repack release_output/AiSummarai_Update.zip
    out_dir = ROOT / "release_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / "AiSummarai_Update.zip"

    exclude_dirs = {
        "data", "build", "dist", "installer_output", "release_output",
        "__pycache__", ".agents", ".git", ".venv", "venv", ".idea", ".vscode", "bin",
    }
    exclude_files = {
        "admin_keygen.py", "ADMIN_KEYGEN.bat",
        "PUSH_UPDATE_TO_GDRIVE.bat", "PUSH_UPDATE_TO_GITHUB.bat",
        "BUILD_INSTALLER.bat", "BUILD_EXE.bat",
    }
    exclude_exts = {
        ".pyc", ".db", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".mp3",
        ".docx", ".log", ".tmp", ".iss",
    }

    if zip_path.exists():
        zip_path.unlink()

    print("[*] Creating AiSummarai_Update.zip...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root_folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
            rel_root = Path(root_folder).relative_to(ROOT)

            for f in files:
                if f.startswith(".") or f in exclude_files:
                    continue
                p = Path(root_folder) / f
                if p.suffix.lower() in exclude_exts:
                    continue
                arcname = str(rel_root / f) if str(rel_root) != "." else f
                zf.write(p, arcname)

    size_kb = round(zip_path.stat().st_size / 1024, 1)
    size_mb = round(size_kb / 1024, 2)
    print(f"[OK] Created {zip_path.name}: {size_kb} KB ({size_mb} MB)")

    # 8. Update both version.json and release_output/version.json with exact file_size_kb
    v_data["file_size_kb"] = size_kb
    v_json_str = json.dumps(v_data, indent=2, ensure_ascii=False)
    v_path.write_text(v_json_str, encoding="utf-8")
    (out_dir / "version.json").write_text(v_json_str, encoding="utf-8")
    if dist_dir.exists():
        shutil.copy2(v_path, dist_dir / "version.json")
    print("[OK] Saved version.json & release_output/version.json")

    print("\n🎉 ALL GITHUB VERSION & PACKAGING TASKS COMPLETED!")


if __name__ == "__main__":
    main()
