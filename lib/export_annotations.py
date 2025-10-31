import os
import re
import argparse
from pathlib import Path
from lib.zotero_annotate import ZoteroClient

def slugify(value: str) -> str:
    """Convert string to lowercase hyphenated slug."""
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')

def ensure_output_dir(path: str) -> Path:
    outdir = Path(path)
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir

def write_markdown_for_item(item, annotations_by_attachment, output_dir: Path):
    """Generate and write a markdown file for a Zotero item."""
    data = item["data"]
    title = data.get("title", "Untitled")
    item_type = data.get("itemType", "document")
    creators = data.get("creators", [])
    year = data.get("date", "")[:4]

    # tags
    author_tags = []
    for c in creators:
        if c.get("creatorType") in ("author", "editor"):
            first = c.get("firstName", "").strip().lower()
            last = c.get("lastName", "").strip().lower()
            if last:
                author_tags.append(f"#{slugify(f'{first}-{last}')}")
    doc_tag = f"#{slugify(item_type)}"

    # prepare filename
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)[:100]
    filename = f"{safe_title or 'untitled'}_{item['key']}.md"
    filepath = output_dir / filename

    # build markdown content
    lines = []
    lines.append(f"# {title}")
    if year:
        lines.append(f"**Year:** {year}")
    lines.append("")
    lines.append(f"**Item Type:** {item_type}")
    if creators:
        names = ", ".join([f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() for c in creators])
        lines.append(f"**Authors:** {names}")
    lines.append("")
    lines.append("**Tags:** " + " ".join(author_tags + [doc_tag]))
    lines.append("\n---\n")

    for entry in annotations_by_attachment.values():
        attachment = entry["attachment"]
        annotations = entry["annotations"]
        att_title = attachment["data"].get("title", "Attachment")

        ann_count = 0
        lines.append(f"## {att_title}")
        for ann in annotations:

            ann_data = ann["data"]
            ann_type = ann_data.get("annotationType", "")
            page = ann_data.get("annotationPageLabel", "")
            text = ann_data.get("annotationText", "")
            comment = ann_data.get("annotationComment", "")
            color = ann_data.get("annotationColor", "")
            lines.append("")
            lines.append(f"### Annotation {ann_count}")
            lines.append(f"**p{page}, type: {ann_type}**")
            lines.append(f"{text}")
            if comment:
                lines.append(f"  > Comment: {comment}")
            if color:
                lines.append(f"  > _(Color: {color})_")
            lines.append("")
            ann_count = ann_count + 1
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Wrote {filepath.name}")


def export():
    parser = argparse.ArgumentParser(description="Export Zotero annotations to Markdown.")
    parser.add_argument("--output-dir", "-o", required=True, help="Directory to save Markdown files")
    parser.add_argument("--limit", "-l", type=int, default=100, help="Limit number of top-level items to fetch")
    args = parser.parse_args()

    output_dir = ensure_output_dir(args.output_dir)
    client = ZoteroClient()

    items = client.query_items(limit=args.limit)
    print(f"📚 Found {len(items)} items.")

    for item in items:
        attachments = client.query_attachments(item["key"])
        annotations_by_attachment = {}
        for att in attachments:
            annotations = client.query_annotations(att["key"])
            if annotations:
                annotations_by_attachment[att["key"]] = {
                    "attachment": att,
                    "annotations": annotations
                }

        if annotations_by_attachment:
            write_markdown_for_item(item, annotations_by_attachment, output_dir)
        else:
            print(f"⚪ No annotations found for: {item['data'].get('title')}")


if __name__ == "__main__":
    export()
