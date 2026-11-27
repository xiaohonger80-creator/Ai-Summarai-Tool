import glob

for p in glob.glob("*.bat"):
    with open(p, "rb") as f:
        data = f.read()
    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with open(p, "wb") as f:
        f.write(data)
    print(f"Normalized CRLF: {p}")
