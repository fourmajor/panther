"""One-time gated download; the token stays in memory, never in login storage."""

import getpass
import os
from pathlib import Path
import sys

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
os.umask(0o077)


def main():
    from huggingface_hub import snapshot_download

    destination = Path.home() / "Library/Application Support/Panther/audio-models/community-1"
    print("Panther: download the free, local Community-1 speaker model.")
    print("Paste your Hugging Face read token below. Input is hidden.")
    print("The token is not saved. No audio is uploaded.")
    if not sys.stdin.isatty():
        raise SystemExit("Run this setup in an interactive terminal.")
    token = getpass.getpass("Hugging Face token: ").strip()
    if not token:
        raise SystemExit("No token entered; nothing downloaded.")
    try:
        snapshot_download(
            "pyannote/speaker-diarization-community-1",
            token=token,
            local_dir=destination,
        )
    except Exception as error:
        # Avoid dumping authenticated request details or a token-bearing traceback.
        print(f"Download failed ({type(error).__name__}). Check access and try again.")
        return 1
    finally:
        token = None
    print(f"Download complete: {destination}")
    print("You can close this terminal. Panther will use these files offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
