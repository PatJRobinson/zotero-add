#!/usr/bin/env python3
"""
zotero_backup.py

Backup a Zotero library to a local directory (metadata, annotations, attachments),
and optionally initialize + commit to a local git repo.

Requirements:
  - Python 3.8+
  - requests

Environment variables:
  - ZOTERO_API_KEY      (required)
  - ZOTERO_LIBRARY_ID  (required)
  - ZOTERO_LIBRARY_TYPE (optional, default: "users")

Usage:
  python zotero_backup.py -o ./zotero_backup --include-attachments --commit
"""

import os
import sys
import json
import time
import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
import requests
from datetime import datetime

API_VERSION = "3"  # using v3 query param in endpoints


def env_get(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(name, default)


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def slugify_name(s: str) -> str:
    # simple slugify to be used if we need readable filenames
    import re
    return re.sub(r"[^0-9a-zA-Z\-_\.]+", "_", s).strip("_")[:150]


class ZoteroBackup:
    def __init__(
        self,
        api_key: str,
        library_id: str,
        library_type: str = "users",
        output_dir: str = "./zotero_backup",
        include_attachments: bool = True,
        commit_repo: bool = True,
        sleep_between_requests: float = 0.5,
        per_page: int = 100,
    ):
        self.api_key = api_key
        self.library_id = library_id
        self.library_type = library_type
        self.base_url = f"https://api.zotero.org/{self.library_type}/{self.library_id}"
        self.output_dir = Path(output_dir)
        self.include_attachments = include_attachments
        self.commit_repo = commit_repo
        self.sleep_between_requests = sleep_between_requests
        self.per_page = per_page

        self.session = requests.Session()
        self.session.headers.update({"Zotero-API-Key": self.api_key, "User-Agent": "zotero_backup_script/1.0"})

        # output subdirs
        self.items_dir = self.output_dir / "items"
        self.attachments_dir = self.output_dir / "attachments"
        self.annotations_dir = self.output_dir / "annotations"
        self.meta_dir = self.output_dir / "meta"

        for d in (self.items_dir, self.attachments_dir, self.annotations_dir, self.meta_dir):
            ensure_dir(d)

    # -------------------------
    # API helpers
    # -------------------------
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None, stream: bool = False):
        url = f"{self.base_url}{path}"
        if params is None:
            params = {}
        # append API version param if not provided
        if "v" not in params:
            params["v"] = API_VERSION
        resp = self.session.get(url, params=params, stream=stream)
        # If rate-limited, raise with info
        if resp.status_code == 429:
            raise RuntimeError("Rate limited by Zotero API (HTTP 429). Consider increasing delays.")
        resp.raise_for_status()
        return resp

    def list_all_items(self) -> List[Dict[str, Any]]:
        """Paginate through every top-level item in the library and return a list of item objects."""
        items = []
        start = 0
        while True:
            params = {"start": start, "limit": self.per_page}
            resp = self._get("/items/top", params=params)
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            print(f"Fetched {len(batch)} items (start={start})")
            start += len(batch)
            time.sleep(self.sleep_between_requests)
            if len(batch) < self.per_page:
                break
        return items

    def get_item(self, item_key: str) -> Dict[str, Any]:
        resp = self._get(f"/items/{item_key}")
        return resp.json()

    def get_item_children(self, item_key: str) -> List[Dict[str, Any]]:
        resp = self._get(f"/items/{item_key}/children")
        return resp.json()

    def get_attachment_file(self, attachment: Dict[str, Any], dest_path: Path) -> bool:
        """
        Try to download the attachment file. Returns True on success.
        The attachment object may contain 'links' pointing to file URL(s).
        We try common link locations such as 'enclosure' or 'file'.
        """
        links = attachment.get("links") or {}
        href = None

        # common link names that can contain downloadable hrefs
        for candidate in ("enclosure", "file", "link", "attachment"):
            link_obj = links.get(candidate)
            if isinstance(link_obj, dict) and link_obj.get("href"):
                href = link_obj.get("href")
                break

        # Sometimes the 'links' field contains a top-level entry with a key we don't know;
        # check first dict entry
        if href is None and isinstance(links, dict) and links:
            first = next(iter(links.values()))
            if isinstance(first, dict) and first.get("href"):
                href = first.get("href")

        if not href:
            # As fallback, try the generic file endpoint (may or may not work depending on server)
            # Format: /items/<attachmentKey>/file
            att_key = attachment.get("key")
            if att_key:
                # This attempts to hit /items/<attKey>/file -- Zotero may require filename appended.
                try:
                    resp = self._get(f"/items/{att_key}/file", stream=True)
                    if resp.status_code == 200:
                        with open(dest_path, "wb") as fh:
                            for chunk in resp.iter_content(chunk_size=8192):
                                if chunk:
                                    fh.write(chunk)
                        return True
                except requests.HTTPError:
                    # ignore and continue
                    pass
            return False

        # If href is relative, make absolute if needed (href might be a full URL already)
        if href.startswith("/"):
            href = f"https://api.zotero.org{href}"

        try:
            print(f"  Downloading file from {href}")
            resp = self.session.get(href, stream=True)
            resp.raise_for_status()
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)
            return True
        except Exception as e:
            print(f"  ⚠️  Failed to download {href}: {e}")
            return False

    # -------------------------
    # Backup process
    # -------------------------
    def backup(self):
        print("Starting Zotero backup")
        items = self.list_all_items()
        meta = {"fetched_at": datetime.utcnow().isoformat() + "Z", "item_count": len(items)}
        (self.meta_dir / "backup_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        for idx, item in enumerate(items, start=1):
            data = item.get("data", {})
            item_key = item.get("key")
            title = data.get("title", f"item-{item_key}")
            print(f"[{idx}/{len(items)}] Backing up item {item_key} — {title}")

            # Save item metadata JSON
            item_file = self.items_dir / f"{item_key}.json"
            item_file.write_text(json.dumps(item, indent=2), encoding="utf-8")

            # Find attachments among children (attachments are child items)
            children = self.get_item_children(item_key)
            time.sleep(self.sleep_between_requests)
            # Attachments and other children
            for child in children:
                cdata = child.get("data", {})
                ctype = cdata.get("itemType", "").lower()
                if ctype == "attachment":
                    att_key = child.get("key")
                    att_title = cdata.get("title") or cdata.get("filename") or f"attachment-{att_key}"
                    att_safe_name = slugify_name(att_title)
                    att_dir = self.attachments_dir / att_key
                    ensure_dir(att_dir)

                    # Save attachment metadata
                    att_meta_file = att_dir / f"{att_key}.json"
                    att_meta_file.write_text(json.dumps(child, indent=2), encoding="utf-8")

                    # Try to download attachment file if requested
                    if self.include_attachments:
                        # determine a filename:
                        # prefer filename from data if present
                        raw_fn = cdata.get("filename") or cdata.get("title") or att_key
                        # try to keep extension if present in filename or link
                        fn = slugify_name(raw_fn)
                        dest_path = att_dir / fn
                        success = self.get_attachment_file(child, dest_path)
                        if not success:
                            # try with att_key as filename and no ext
                            dest_path2 = att_dir / f"{att_key}"
                            success2 = self.get_attachment_file(child, dest_path2)
                            if success2:
                                print(f"    saved as {dest_path2.name}")
                            else:
                                print(f"    skipped downloading attachment {att_key}")
                        else:
                            print(f"    saved file {dest_path.name}")

                    # fetch annotations children for this attachment
                    try:
                        ann_children = self.get_item_children(att_key)
                        time.sleep(self.sleep_between_requests)
                        if ann_children:
                            ann_file = self.annotations_dir / f"{att_key}.json"
                            ann_file.write_text(json.dumps(ann_children, indent=2), encoding="utf-8")
                            print(f"    saved {len(ann_children)} annotation(s)")
                    except Exception as e:
                        print(f"    failed to fetch children for attachment {att_key}: {e}")

            # End of item loop

        print("Backup complete.")

        if self.commit_repo:
            self._maybe_init_and_commit()

    # -------------------------
    # Git helpers
    # -------------------------
    def _is_git_repo(self) -> bool:
        try:
            subprocess.run(["git", "-C", str(self.output_dir), "rev-parse"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _maybe_init_and_commit(self):
        # initialize repo if needed
        if not self._is_git_repo():
            print("Initializing git repo in output directory...")
            try:
                subprocess.run(["git", "init", str(self.output_dir)], check=True)
            except Exception as e:
                print(f"Failed to init git repo: {e}")
                return

        # .gitignore: ignore nothing by default, but we will create a recommended one
        gi_path = self.output_dir / ".gitignore"
        if not gi_path.exists():
            gi_path.write_text("\n# Example .gitignore - adjust as needed\n__pycache__/\n*.pyc\n", encoding="utf-8")

        # Add and commit
        try:
            subprocess.run(["git", "-C", str(self.output_dir), "add", "."], check=True)
            msg = f"Zotero backup {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}"
            subprocess.run(["git", "-C", str(self.output_dir), "commit", "-m", msg], check=True)
            print("Committed backup to git.")
        except subprocess.CalledProcessError as e:
            print("git add/commit failed (maybe nothing to commit).", e)


def backup():
    parser = argparse.ArgumentParser(description="Backup Zotero library (metadata, annotations, attachments) into a local repo directory.")
    parser.add_argument("-o", "--output-dir", required=True, help="Directory to store backup")
    parser.add_argument("--no-attachments", dest="include_attachments", action="store_false", help="Do not download attachment files")
    parser.add_argument("--no-commit", dest="commit_repo", action="store_false", help="Do not init/commit a git repo")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between requests (default 0.5)")
    parser.add_argument("--per-page", type=int, default=100, help="Items per page to fetch from API (default 100)")
    args = parser.parse_args()

    api_key = env_get("ZOTERO_API_KEY")
    lib_id = env_get("ZOTERO_LIBRARY_ID")
    lib_type = env_get("ZOTERO_LIBRARY_TYPE", "users")

    if not api_key or not lib_id:
        print("Missing environment variables. Set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID.")
        sys.exit(2)

    zb = ZoteroBackup(
        api_key=api_key,
        library_id=lib_id,
        library_type=lib_type,
        output_dir=args.output_dir,
        include_attachments=args.include_attachments,
        commit_repo=args.commit_repo,
        sleep_between_requests=args.sleep,
        per_page=args.per_page,
    )

    try:
        zb.backup()
    except KeyboardInterrupt:
        print("Interrupted by user.")
    except Exception as e:
        print("Error during backup:", e)
        raise


if __name__ == "__main__":
    backup()
