# zotero_add

A lightweight command-line tool for adding papers to [Zotero](https://www.zotero.org) without needing the browser extension.

Due to pyzotero not being packaged on nixpkgs, it uses the python requests library to talk to the zotero API directly.

It can:

- Create Zotero items from web URLs or local PDF files
- Extract metadata automatically (title, authors, DOI, year) from PDFs
- Attach the original PDF to the Zotero item

---

## Requirements

- **Zotero account** (with API key and library ID)  
- **Python 3.11+**  
- Libraries:
  - `requests`
  - `beautifulsoup4`
  - `pymupdf` (aka `fitz`) – used for PDF text extraction  
  - `crossrefapi` *(optional, but helps with DOI lookups)*

On NixOS:

```bash
nix-shell -p "python3.withPackages (ps: [ps.requests ps.beautifulsoup4 ps.pymupdf])"
```

On other distros:

```bash
pip install requests beautifulsoup4 pymupdf
```

---

## Configuration

Export your Zotero API credentials (recommended via shell profile):

```bash
export ZOTERO_API_KEY="your-api-key"
export ZOTERO_LIBRARY_ID="your-user-or-group-id"
export ZOTERO_LIBRARY_TYPE="user"   # or "group"
```

You can generate an API key in [Zotero Settings → Feeds/API](https://www.zotero.org/settings/keys).

---

## Usage

### Add a PDF (with metadata + attachment)

```bash
./zotero_add ~/Downloads/paper.pdf
```

- Extracts metadata from the PDF text (title, authors, year, DOI)
- Creates a `journalArticle` item in Zotero
- Uploads and attaches the PDF as a child item

### Add a webpage

```bash
./zotero_add "https://example.org/some-article"
```

- Creates a `webpage` item with title + URL

---

## How it works

1. **Metadata extraction**  
   - For PDFs: extract text with `pymupdf` → look for DOI via regex → fetch metadata from Crossref (if available).  
   - For webpages: parse `<title>` with BeautifulSoup.

2. **Item creation**  
   - Posts a JSON item to Zotero’s API (`/users/<id>/items`).

3. **Attachment upload**  
   - Creates a child `attachment` item (`imported_file` linkMode).  
   - Runs the multi-step file upload flow (`/file` endpoint with uploadKey, md5, etc.).  
   - Registers the file once uploaded.

---

## Example

```bash
$ ./zotero_add ~/Downloads/entanglement-hci-the-next-wave.pdf
Created item: WJKQ2E6C
Upload complete: entanglement-hci-the-next-wave.pdf
```

---

## Troubleshooting

- **400 errors**: usually caused by malformed payloads — check your `parentItem` and API key
- **Attachment not uploaded**: ensure `pymupdf` can read the PDF and Zotero’s file upload flow completes
- Run with `print` debugging enabled to inspect server responses

---
