#!/usr/bin/env python3
"""
scrape.py – Pharma-industry RFP harvester
========================================
* Visits each landing page listed in SITES
* Finds links to .pdf, .doc, and .docx files.
* Downloads new docs into ./data/<sha1>.<ext>
* Extracts "Issued / Deadline" dates from page 1 of PDFs and DOCX files.
* Merges everything into latest_rfps.json for GPT ingestion
"""

from __future__ import annotations
import hashlib, json, re, pathlib, logging, datetime
import requests, pdfplumber, docx  ## NEW: import docx
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------
# 0. Settings
# ---------------------------------------------------------------------
SITES = {
    "samsung": "https://sra.samsung.com/collaboration/start/apply/",
    "amazon":  "https://www.amazon.science/research-awards/call-for-proposals",
    "nvidia": "https://www.nvidia.com/en-in/industries/higher-education-research/academic-grant-program/",
    "cisco": "https://research.cisco.com/open-rfps",
    "google": "https://research.google/programs-and-events/research-scholar-program/",
    "opentech": "https://www.opentech.fund/funds/",
    "aisi": "https://www.aisi.gov.uk/grants",
    "shell": "http://shell.com/what-we-do/technology-and-innovation/innovate-with-shell/shell-gamechanger/call-for-proposals.html#:~:text=Our%20areas%20of%20interest%20,for%20proposals%20are%20now%20open",
    "darpa": "https://www.darpa.mil/work-with-us/opportunities",
    "Johnson&Johnson": "https://jnjinnovation.com/innovation-challenges",
    "M-ERA NET": "https://www.m-era.net/joint-calls",
    "Boehringer Ingelheim": "https://www.opnme.com/",
    "Halton Foundation": "https://foundation.halton.com/halton-foundation-grant-application/"
}

DATA_DIR  = pathlib.Path("data")
JSON_PATH = pathlib.Path("latest_rfps.json")
DATA_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ---------------------------------------------------------------------
# 1. Retry-capable requests.Session
# ---------------------------------------------------------------------
def build_session(retries: int = 3, backoff: int = 2, timeout: int = 30) -> requests.Session:
    sess = requests.Session()
    retry_cfg = Retry(
        total=retries, read=retries, connect=retries,
        backoff_factor=backoff, status_forcelist=[502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_cfg)
    sess.mount("https://", adapter)
    sess.mount("http://",  adapter)
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    })
    return sess

session = build_session()

# ---------------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------------
PDF_RE = re.compile(r"https://[^\s\"']+\.pdf", re.I)
date_pat = re.compile(r"(Issued|Posted):\s*([\d\w ,-]+)", re.I)
ddl_pat  = re.compile(r"(Deadline|Due):\s*([\d\w ,-]+)", re.I)

def doc_links(url: str):
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except RequestException as e:
        logging.warning(f"SKIP {url} ↯ {e}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    found_links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith((".pdf", ".doc", ".docx")):
            full_url = href if href.startswith("http") else requests.compat.urljoin(url, href)
            found_links.add(full_url)

    if not found_links:
        for m in PDF_RE.findall(resp.text):
            found_links.add(m)
    yield from found_links

def parse_pdf(path: pathlib.Path) -> dict[str, str]:
    """Return {posted, deadline, snippet} from first ~1500 chars of a PDF."""
    try:
        with pdfplumber.open(path) as pdf:
            txt = (pdf.pages[0].extract_text(x_tolerance=2) or "")[:1500]
    except Exception as e:
        logging.warning(f"⚠️  PDF parse failed for {path.name}: {e}")
        return {"posted": "n/a", "deadline": "n/a", "snippet": f"Error parsing PDF: {e}"}

    posted   = date_pat.search(txt)
    deadline = ddl_pat.search(txt)
    return {
        "posted":   posted.group(2).strip()   if posted   else "n/a",
        "deadline": deadline.group(2).strip() if deadline else "n/a",
        "snippet":  " ".join(txt.replace("\n", " ").split()[:60]),
    }

## NEW: Add a parser specifically for .docx files ##
def parse_docx(path: pathlib.Path) -> dict[str, str]:
    """Return {posted, deadline, snippet} from first ~1500 chars of a DOCX."""
    try:
        doc = docx.Document(path)
        full_text = "\n".join([para.text for para in doc.paragraphs])
        txt = full_text[:1500]
    except Exception as e:
        logging.warning(f"⚠️  DOCX parse failed for {path.name}: {e}")
        return {"posted": "n/a", "deadline": "n/a", "snippet": f"Error parsing DOCX: {e}"}

    posted   = date_pat.search(txt)
    deadline = ddl_pat.search(txt)
    return {
        "posted":   posted.group(2).strip()   if posted   else "n/a",
        "deadline": deadline.group(2).strip() if deadline else "n/a",
        "snippet":  " ".join(txt.replace("\n", " ").split()[:60]),
    }

# ---------------------------------------------------------------------
# 3. Main driver
# ---------------------------------------------------------------------
def main() -> None:
    ts = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    logging.info("🌀  Scraper start %s", ts)

    newly_scraped_rfps: list[dict] = []
    ## MODIFIED: Check all file types in the data directory, not just PDFs. ##
    seen_hashes = {p.stem for p in DATA_DIR.glob("*.*")}

    for tag, url in SITES.items():
        logging.info("🌐  %-10s → %s", tag, url)
        for link in doc_links(url):
            h = hashlib.sha1(link.encode()).hexdigest()
            if h in seen_hashes:
                continue

            logging.info("⬇️   Downloading %s", link)
            try:
                response = session.get(link, timeout=30)
                response.raise_for_status()
            except RequestException as e:
                logging.warning("⚠️  Download failed %s: %s", link, e)
                continue
            
            ## MODIFIED: Save file with its original extension ##
            file_ext = pathlib.Path(link).suffix.lower()
            if not file_ext in [".pdf", ".docx", ".doc"]: # Sanity check
                logging.warning(f"⚠️  Skipping unknown file type: {link}")
                continue

            file_path = DATA_DIR / f"{h}{file_ext}"
            file_path.write_bytes(response.content)
            
            meta = {}
            ## MODIFIED: Call the correct parser based on file type ##
            if file_ext == ".pdf":
                meta = parse_pdf(file_path)
            elif file_ext == ".docx":
                meta = parse_docx(file_path)
            elif file_ext == ".doc":
                logging.info(f"ℹ️   Downloaded legacy .doc file, cannot parse text: {link}")
                meta = {"posted": "n/a", "deadline": "n/a", "snippet": "Legacy .doc file, text extraction not supported."}

            meta["portal"] = tag
            meta["source"] = link
            newly_scraped_rfps.append(meta)

    # Load existing JSON robustly
    existing_rfps = []
    if JSON_PATH.exists() and JSON_PATH.stat().st_size > 0:
        try:
            existing_rfps = json.loads(JSON_PATH.read_text())
        except json.JSONDecodeError:
            logging.warning(f"⚠️  Could not decode {JSON_PATH}. Starting fresh.")
    
    # Merge and deduplicate
    final_rfps_dict = {item['source']: item for item in existing_rfps}
    for item in newly_scraped_rfps:
        final_rfps_dict[item['source']] = item
    final_rfps_list = list(final_rfps_dict.values())
    
    logging.info(f"✅  Found {len(newly_scraped_rfps)} new documents. Total is now {len(final_rfps_list)}.")
    JSON_PATH.write_text(json.dumps(final_rfps_list, indent=2))
    logging.info(f"✅  Wrote {len(final_rfps_list)} total RFP entries to {JSON_PATH}")


if __name__ == "__main__":
    main()
