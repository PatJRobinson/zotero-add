import os
import requests
from typing import List, Dict, Optional


class ZoteroClient:
    """
    Lightweight client for accessing Zotero annotations via the Web API.

    Environment variables:
        ZOTERO_API_KEY     - Your Zotero API key (read access at minimum)
        ZOTERO_LIBRARY_ID  - Your user or group library ID
        ZOTERO_LIBRARY_TYPE - "users" (default) or "groups"
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        library_id: Optional[str] = None,
        library_type: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ZOTERO_API_KEY")
        self.library_id = library_id or os.getenv("ZOTERO_LIBRARY_ID")
        self.library_type = library_type or os.getenv("ZOTERO_LIBRARY_TYPE", "users")

        if not self.api_key:
            raise ValueError("Missing Zotero API key (set ZOTERO_API_KEY or pass api_key).")
        if not self.library_id:
            raise ValueError("Missing Zotero library ID (set ZOTERO_LIBRARY_ID or pass library_id).")

        self.base_url = f"https://api.zotero.org/{self.library_type}/{self.library_id}"
        self.session = requests.Session()
        self.session.headers.update({"Zotero-API-Key": self.api_key})

    # ----------------------------
    # Core API query helpers
    # ----------------------------
    def query_items(self, top: bool = True, limit: int = 100) -> List[Dict]:
        """Fetch top-level (or all) items in the library."""
        url = f"{self.base_url}/items"
        if top:
            url += "/top"
        params = {"limit": limit}
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def query_attachments(self, item_key: str) -> List[Dict]:
        """Return attachment items for a given library item."""
        url = f"{self.base_url}/items/{item_key}/children"
        response = self.session.get(url)
        response.raise_for_status()
        return [
            i for i in response.json() if i["data"].get("itemType") == "attachment"
        ]

    def query_annotations(self, attachment_key: str) -> List[Dict]:
        """Return annotation items under a given attachment."""
        url = f"{self.base_url}/items/{attachment_key}/children"
        response = self.session.get(url)
        response.raise_for_status()
        return [
            i for i in response.json() if i["data"].get("itemType") == "annotation"
        ]

    def get_all_annotations(self, limit: int = 100) -> List[Dict]:
        """Fetch all annotations across top-level items (limited by pagination)."""
        all_annotations = []
        items = self.query_items(limit=limit)
        for item in items:
            attachments = self.query_attachments(item["key"])
            for att in attachments:
                annotations = self.query_annotations(att["key"])
                all_annotations.extend(annotations)
        return all_annotations
