from zotero_annotate import ZoteroClient

client = ZoteroClient()
annotations = client.get_all_annotations(limit=50)

for ann in annotations:
    data = ann["data"]
    print(f"[{data.get('pageLabel')}] {data.get('annotationText')}")
    if comment := data.get("annotationComment"):
        print(f"  Comment: {comment}")
    print()
