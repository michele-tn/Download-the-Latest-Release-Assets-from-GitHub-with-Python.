from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


CHUNK_SIZE = 1024 * 1024
SCRIPT_DIRECTORY = Path(__file__).resolve().parent


def safe_path_component(value: str, fallback: str) -> str:
    """Return a Windows-safe file or directory name component."""
    sanitized_value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return sanitized_value or fallback


def release_directory(release_tag: str) -> Path:
    """Return a Windows-safe output directory for a release tag."""
    safe_tag = safe_path_component(release_tag, "senza tag")
    return SCRIPT_DIRECTORY / f"Assets release {safe_tag}"


def github_headers() -> dict[str, str]:
    """Return headers for GitHub API and asset requests."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "download-assets-script",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def download_file(url: str, destination: Path, headers: dict[str, str]) -> None:
    """Download an URL atomically to destination."""
    temporary_path = destination.with_name(f".{destination.name}.part")
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            with temporary_path.open("wb") as output_file:
                while chunk := response.read(CHUNK_SIZE):
                    output_file.write(chunk)
        temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def download_github_assets(owner: str, repo: str, release_tag: str) -> bool:
    """Download every asset into a release-specific directory."""
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}/releases/"
        f"tags/{release_tag}"
    )
    headers = github_headers()
    request = urllib.request.Request(api_url, headers=headers)

    print(f"Connessione a GitHub per {owner}/{repo} (release {release_tag})...")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.reason
        try:
            payload = json.loads(error.read().decode("utf-8"))
            detail = payload.get("message", detail)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        print(f"Errore API GitHub: HTTP {error.code} - {detail}", file=sys.stderr)
        return False
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"Errore durante la connessione a GitHub: {error}", file=sys.stderr)
        return False

    assets = [
        (Path(asset["name"]).name, asset["browser_download_url"])
        for asset in release.get("assets", [])
    ]
    safe_repo = safe_path_component(repo, "repository")
    safe_tag = safe_path_component(release_tag, "release")
    source_archives = [
        (f"{safe_repo}-{safe_tag}-source.zip", release["zipball_url"]),
        (f"{safe_repo}-{safe_tag}-source.tar.gz", release["tarball_url"]),
    ]
    downloads = assets + source_archives

    destination_directory = release_directory(release_tag)
    destination_directory.mkdir(parents=True, exist_ok=True)
    print(
        f"Trovati {len(assets)} asset e {len(source_archives)} archivi sorgente "
        f"({len(downloads)} file totali). Destinazione: {destination_directory}"
    )

    failures = 0
    for index, (file_name, download_url) in enumerate(downloads, start=1):
        destination = destination_directory / file_name
        print(f"[{index}/{len(downloads)}] Download di {file_name}...")
        try:
            download_file(download_url, destination, headers)
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            failures += 1
            print(f"Errore durante il download di {file_name}: {error}", file=sys.stderr)

    if failures:
        print(f"Download terminato con {failures} errore/i.", file=sys.stderr)
        return False

    print(f"Download completato: {len(downloads)} file scaricati.")
    return True


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Scarica tutti gli asset di una release GitHub in una sottocartella "
            "dedicata accanto allo script."
        )
    )
    parser.add_argument("owner", nargs="?", help="Proprietario del repository")
    parser.add_argument("repo", nargs="?", help="Nome del repository")
    parser.add_argument("tag", nargs="?", help="Tag della release")
    args = parser.parse_args()

    provided_values = (args.owner, args.repo, args.tag)
    if any(provided_values) and not all(provided_values):
        parser.error(
            "specificare tutti i parametri: <AUTORE> <PROGETTO> <RELEASE>, "
            "oppure avviare lo script senza parametri"
        )
    return args


def prompt_required_value(label: str) -> str:
    """Prompt until the user enters a non-empty value."""
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("Il valore non può essere vuoto.")


def interactive_parameters() -> tuple[str, str, str]:
    """Collect repository and release parameters interactively."""
    print("GitHub Release Assets Downloader")
    print("Inserire i dati della release da scaricare.\n")
    owner = prompt_required_value("Autore / organizzazione")
    repo = prompt_required_value("Nome progetto / repository")
    tag = prompt_required_value("Release / tag")
    print()
    return owner, repo, tag


def main() -> int:
    """Run the command-line application."""
    args = parse_args()
    try:
        owner, repo, tag = (
            (args.owner, args.repo, args.tag)
            if args.owner is not None
            else interactive_parameters()
        )
    except (EOFError, KeyboardInterrupt):
        print("\nOperazione annullata.", file=sys.stderr)
        return 130

    return 0 if download_github_assets(owner, repo, tag) else 1


if __name__ == "__main__":
    raise SystemExit(main())
