import os

for root, dirs, files in os.walk("."):
    if any(x in root for x in [".git", "__pycache__", "build", "dist", ".agents"]):
        continue
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(root, f)
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                for i, line in enumerate(fp):
                    if '["id"]' in line or "['id']" in line or '.get("id")' in line or ".get('id')" in line:
                        if '["id"]' in line or "['id']" in line:
                            print(f"{p}:{i+1}: {line.strip()}")
