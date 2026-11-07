"""Verify all delivered files against the release manifest using only Python."""
import hashlib
import json
from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "SHA256SUMS.json").read_text(encoding="utf-8"))
    failed = []
    for name, expected in manifest.items():
        file = (root / name).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            failed.append(name)
            continue
        with file.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            failed.append(name)
    print(f"Verified {len(manifest)} delivered files; mismatches: {len(failed)}")
    for name in failed:
        print(name)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
