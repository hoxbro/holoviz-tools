from __future__ import annotations

import os
import platform
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import rich
from rich.progress import Progress

CHROME_VERSION = 141
CACHE_DIR = Path.home() / ".cache" / "chrome-dev"
CHROME_DIR = CACHE_DIR / f"chrome-{CHROME_VERSION}"
CHROME_SYMLINK = Path.home() / ".local" / "bin" / "chrome-dev"

match platform.system():
    case "Windows":
        PLATFORM = "win64"
    case "Darwin":
        PLATFORM = "mac-arm64"
    case "Linux":
        PLATFORM = "linux64"
    case other:
        msg = f"Unsupported OS: {other}"
        raise RuntimeError(msg)


def get_url() -> str:
    json_url = "https://googlechromelabs.github.io/chrome-for-testing/latest-versions-per-milestone-with-downloads.json"
    data = httpx.get(json_url).raise_for_status().json()
    return next(
        item["url"]
        for item in data["milestones"][str(CHROME_VERSION)]["downloads"]["chrome"]
        if item["platform"] == PLATFORM
    )


def download_zip(url) -> BytesIO:
    with httpx.Client() as client, client.stream("GET", url) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = BytesIO()

        with Progress() as progress:
            task = progress.add_task("Downloading Chrome", total=total)

            for chunk in response.iter_bytes(chunk_size=1024):
                downloaded.write(chunk)
                progress.update(task, advance=len(chunk))

        downloaded.seek(0)
    return downloaded


def unzip(downloaded: BytesIO):
    CHROME_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(downloaded, "r") as zip_ref:
        total_files = len(zip_ref.infolist())

        with Progress() as progress:
            task = progress.add_task("Extracting Chrome ", total=total_files)

            for file_info in zip_ref.infolist():
                parts = Path(file_info.filename).parts
                if len(parts) > 1:
                    relative_path = Path(*parts[1:])
                    extracted_path = CHROME_DIR / relative_path

                    if file_info.is_dir():
                        extracted_path.mkdir(parents=True, exist_ok=True)
                    else:
                        extracted_path.parent.mkdir(parents=True, exist_ok=True)
                        with (
                            zip_ref.open(file_info) as source,
                            open(extracted_path, "wb") as target,
                        ):
                            target.write(source.read())

                        os.chmod(extracted_path, file_info.external_attr >> 16)

                    progress.update(task, advance=1)


def main():
    if not CHROME_DIR.exists():
        rich.print(f"[red]Did not find Chrome ({CHROME_VERSION}), downloading it now.")
        url = get_url()
        downloaded = download_zip(url)
        unzip(downloaded)
    else:
        rich.print(f"[green]Found Chrome ({CHROME_VERSION})")

    CHROME_SYMLINK.unlink(missing_ok=True)
    CHROME_SYMLINK.symlink_to(CHROME_DIR / "chrome")


if __name__ == "__main__":
    main()
