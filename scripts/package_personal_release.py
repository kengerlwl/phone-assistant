"""Package APK and AGPL source using Git exclusions plus a separate private-file denylist."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release"
EXCLUDED = {".git", ".gradle", ".private", ".venv", ".idea", "build", "release", "verification", "output", "__pycache__", ".catpaw"}
PRIVATE_SUFFIXES = {".jks", ".keystore", ".apk", ".pyc", ".p12", ".pfx", ".pem", ".key"}


def public_source_files():
    candidates = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    ).decode().split("\0")
    files = []
    for name in sorted(set(filter(None, candidates))):
        rel = Path(name)
        path = ROOT / rel
        private = any(part in EXCLUDED or part.startswith("tmp") for part in rel.parts)
        private = private or rel.parts[:2] in {("deploy", "data"), ("deploy", "tls")}
        private = private or path.name in {"local.properties", ".DS_Store", "bridge.env", "SKILL.md"}
        private = private or path.name.startswith(("._", ".env")) or path.suffix.lower() in PRIVATE_SUFFIXES
        if private or path.is_symlink() or not path.is_file():
            continue
        files.append((path, rel))
    if not {"LICENSE", "README.md", "bridge/server.py", "deploy/compose.yaml"}.issubset({str(rel) for _, rel in files}):
        raise RuntimeError("Missing required public source files")
    return files


def main():
    metadata_file = ROOT / "app/build/outputs/apk/release/output-metadata.json"
    metadata = json.loads(metadata_file.read_text())
    element = metadata["elements"][0]
    version = element["versionName"]
    apk = metadata_file.parent / element["outputFile"]
    if not apk.is_file():
        raise RuntimeError("Build a signed release APK first")
    OUT.mkdir(exist_ok=True)
    delivered = OUT / f"phone-assistant-{version}.apk"
    shutil.copy2(apk, delivered)
    files = public_source_files()
    source = OUT / f"phone-assistant-{version}-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, rel in files:
            archive.write(path, Path("phone-assistant") / rel)
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Source archive integrity failed")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [delivered, source]}
    (OUT / "SHA256SUMS.txt").write_text("".join(f"{v}  {k}\n" for k, v in hashes.items()))
    info = {"version": version, "applicationId": metadata["applicationId"],
            "upstream": "Mobilerun Portal v0.7.25", "upstreamCommit": "d4cb7d6657385488239812e776df584f890e32fd",
            "sourceFileCount": len(files), "hashes": hashes,
            "exclusions": sorted(EXCLUDED), "verification": "Packaging is not device acceptance; see this version's verification record."}
    (OUT / "release-manifest.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
