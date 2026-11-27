# Ai Summarai Studio — Official GitHub Update Server

Official repository and in-app auto-update distribution server for **Ai Summarai Studio** (`v1.6.5`).

## Auto-Update Endpoints
- **Manifest (`version.json`)**:
  `https://raw.githubusercontent.com/xiaohonger80-creator/Ai-Summarai-Tool/main/version.json`
- **Update Package (`AiSummarai_Update.zip`)**:
  `https://raw.githubusercontent.com/xiaohonger80-creator/Ai-Summarai-Tool/main/release_output/AiSummarai_Update.zip`

## Developer Release Workflow
Run `PUSH_UPDATE_TO_GITHUB.bat` (or `python tools/push_to_github.py`) to:
1. Bump version numbers across `core/updater.py`, `updater_config.json`, `version.json`, `version_info.txt`, and `AiSummarai_Installer.iss`.
2. Build a clean `release_output/AiSummarai_Update.zip` (protecting user `data/` and excluding admin/build files).
3. Commit and push directly to `main` so all Ai Summarai installations receive the update automatically.
