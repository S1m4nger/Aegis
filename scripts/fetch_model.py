"""Fetch the explicitly pinned trusted LR bundle; verify bytes before installation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

FILES = {"model.joblib", "calibrator.joblib", "metadata.json"}
MAX_FILE_SIZE = 8 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Artifact redirects are not permitted")


def read_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported artifact manifest schema")
    version, commit = manifest.get("model_version", ""), manifest.get("artifact_commit", "")
    if (not isinstance(version, str) or not isinstance(commit, str)
            or not re.fullmatch(r"paysim-lr-[0-9a-f]{16}", version)
            or not re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise ValueError("An explicit frozen LR version and immutable artifact commit are required")
    expected = f"https://raw.githubusercontent.com/S1m4nger/Aegis/{commit}/models/{version}"
    if manifest.get("base_url") != expected:
        raise ValueError("Artifact origin must be the pinned Aegis GitHub commit")
    if (not isinstance(manifest.get("source_dataset_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["source_dataset_sha256"])):
        raise ValueError("The original training-source digest is required")
    files = manifest.get("files", {})
    if not isinstance(files, dict) or set(files) != FILES:
        raise ValueError("Artifact manifest must contain exactly the three frozen files")
    for name, info in files.items():
        if (not isinstance(info, dict) or not isinstance(info.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"])
                or isinstance(info.get("size"), bool) or not isinstance(info.get("size"), int)
                or not 0 < info["size"] <= MAX_FILE_SIZE):
            raise ValueError(f"Invalid artifact digest or size: {name}")
    return manifest


def verify(contents, manifest):
    for name, data in contents.items():
        expected = manifest["files"][name]
        if len(data) != expected["size"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError(f"Artifact integrity check failed: {name}")
    if set(contents) != FILES:
        raise ValueError("Incomplete artifact bundle")
    metadata = json.loads(contents["metadata.json"])
    if (metadata.get("model_version") != manifest["model_version"]
            or metadata.get("feature_names") != ["type", "amount_log", "hour"]
            or metadata.get("model_sha256") != manifest["files"]["model.joblib"]["sha256"]
            or metadata.get("calibrator_sha256") != manifest["files"]["calibrator.joblib"]["sha256"]
            or metadata.get("source_sha256") != manifest.get("source_dataset_sha256")):
        raise ValueError("Frozen metadata does not match the bundle provenance")


def fetch(manifest_path, output, check_only=False):
    manifest = read_manifest(manifest_path)
    output = Path(output)
    if output.is_symlink():
        raise ValueError("Artifact output cannot be a symlink")
    if output.exists() and (not output.is_dir() or any((output / name).exists() or (output / name).is_symlink() for name in FILES)):
        # Existing original bundles are verified and reused, never overwritten.
        contents = {}
        for name in FILES:
            path = output / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_SIZE:
                raise ValueError("Existing artifact bundle is incomplete or unsafe; it will not be overwritten")
            contents[name] = path.read_bytes()
        verify(contents, manifest)
        return manifest["model_version"]
    if check_only:
        raise ValueError("Artifact bundle is missing")
    opener = urllib.request.build_opener(NoRedirect())
    contents = {}
    for name in sorted(FILES):
        request = urllib.request.Request(manifest["base_url"] + "/" + name,
                                         headers={"User-Agent": "Aegis-model-fetch/1"})
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise ValueError(f"Artifact download failed: {name}")
            contents[name] = response.read(manifest["files"][name]["size"] + 1)
    verify(contents, manifest)
    # All remote bytes and metadata have passed verification before any file appears.
    output.parent.mkdir(parents=True, exist_ok=True)
    created_directory = not output.exists()
    output.mkdir(exist_ok=True)  # README-only source directories are valid destinations.
    created = []
    try:
        for name, data in contents.items():
            with (output / name).open("xb") as stream:
                created.append(output / name)
                stream.write(data)
    except BaseException:
        for path in created:
            path.unlink()
        if created_directory:
            output.rmdir()
        raise
    return manifest["model_version"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--manifest", type=Path, default=root / "configs/model-artifacts.json")
    parser.add_argument("--output", type=Path, default=root / "services/ml/artifacts")
    parser.add_argument("--check", action="store_true", help="Verify existing files without networking")
    args = parser.parse_args()
    try:
        version = fetch(args.manifest, args.output, args.check)
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        parser.exit(1, f"Model artifact preparation failed: {type(error).__name__}: {error}\n")
    print(f"Verified frozen model: {version}")


if __name__ == "__main__":
    main()
