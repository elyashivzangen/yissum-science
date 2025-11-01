#!/usr/bin/env python3
"""
scrape.py – Pharma-industry RFP harvester
========================================
* Visits each landing page listed in SITES
* Finds links to .pdf (and gracefully ignores .doc/.docx)
* Downloads new docs into ./data/<sha1>.pdf
* Extracts "Issued / Deadline" dates from page 1
* Merges everything into latest_rfps.json for GPT ingestion
"""

from __future__ import annotations
import hashlib, json, re, pathlib, logging, datetime
import requests, pdfplumber
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

# Make sure DATA_DIR exists from the start
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
    # This attribute is not standard for requests.Session, but we can set it for our use.
    # It seems you intended to use it with `session.get(..., timeout=session.request_timeout)`
    # The timeout parameter should be passed directly to the get method.
    # We will pass the timeout value directly in the get calls.
    return sess

session = build_session()

# ---------------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------------
PDF_RE = re.compile(r"https://[^\s\"']+\.pdf", re.I)
date_pat = re.compile(r"(Issued|Posted):\s*([\d\w ,-]+)", re.I)
ddl_pat  = re.compile(r"(Deadline|Due):\s*([\d\w ,-]+)", re.I)

def doc_links(url: str):
    """
    Yield absolute URLs for every PDF / Word doc found on `url`.
    Network errors are logged and swallowed.
    """
    try:
        resp = session.get(url, timeout=30) # Pass timeout directly
        resp.raise_for_status()
    except RequestException as e:
        logging.warning(f"SKIP {url} ↯ {e}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    found_links = set() # Use a set to auto-handle duplicates on a page

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
    """Return {posted, deadline, snippet} from first ~1500 chars."""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise ValueError("PDF has no pages.")
            txt = pdf.pages[0].extract_text(x_tolerance=2) or ""
            txt = txt[:1500]
    except Exception as e:
        logging.warning(f"⚠️  PDF parse failed for {path.name}: {e}")
        return {"posted": "n/a", "deadline": "n/a", "snippet": f"Error parsing PDF: {e}"}

    posted   = date_pat.search(txt)
    deadline = ddl_pat.search(txt)
    return {
        "posted":   posted.group(2).strip()   if posted   else "n/a",
        "deadline": deadline.group(2).strip() if deadline else "n/a",
        "snippet":  " ".join(txt.replace("\n", " ").split()[:60]), # Create a clean, space-separated snippet
    }

# ---------------------------------------------------------------------
# 3. Main driver
# ---------------------------------------------------------------------
def main() -> None:
    ts = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    logging.info("🌀  Scraper start %s", ts)

    newly_scraped_rfps: list[dict] = []
    seen_hashes = {p.stem for p in DATA_DIR.glob("*.pdf")}

    for tag, url in SITES.items():
        logging.info("🌐  %-10s → %s", tag, url)
        for link in doc_links(url):
            # --- FIX 1: Gracefully skip non-PDF files ---
            if not link.lower().endswith(".pdf"):
                logging.info("ℹ️   Skipping non-PDF link: %s", link)
                continue

            h = hashlib.sha1(link.encode()).hexdigest()
            if h in seen_hashes:
                continue

            logging.info("⬇️   Downloading %s", link)
            try:
                pdf_response = session.get(link, timeout=30)
                pdf_response.raise_for_status()
                pdf_bytes = pdf_response.content
            except RequestException as e:
                logging.warning("⚠️  Download failed %s: %s", link, e)
                continue

            file_path = DATA_DIR / f"{h}.pdf"
            file_path.write_bytes(pdf_bytes)
            
            meta = parse_pdf(file_path)
            meta["portal"] = tag
            meta["source"] = link
            newly_scraped_rfps.append(meta)

    # --- FIX 2: Robustly load existing JSON, even if empty or corrupted ---
    existing_rfps = []
    if JSON_PATH.exists():
        try:
            # Only try to load if the file is not empty
            if JSON_PATH.stat().st_size > 0:
                existing_rfps = json.loads(JSON_PATH.read_text())
            else:
                logging.info(f"ℹ️  {JSON_PATH} is empty. Starting fresh.")
        except json.JSONDecodeError:
            logging.warning(f"⚠️  Could not decode {JSON_PATH}. It may be corrupted. Starting fresh.")
    
    # --- FIX 3: Improved merge and deduplication logic ---
    # Create a dictionary of existing RFPs for quick lookups
    final_rfps_dict = {item['source']: item for item in existing_rfps}
    
    # Update the dictionary with newly scraped items.
    # This overwrites any old entries with fresh data if the source URL is the same.
    for item in newly_scraped_rfps:
        final_rfps_dict[item['source']] = item
        
    # Convert the dictionary back to a list
    final_rfps_list = list(final_rfps_dict.values())
    
    logging.info(f"✅  Found {len(newly_scraped_rfps)} new RFPs. Total is now {len(final_rfps_list)}.")

    # Always write the result. If no RFPs are found, this will create an empty JSON array `[]`.
    JSON_PATH.write_text(json.dumps(final_rfps_list, indent=2))
    logging.info(f"✅  Wrote {len(final_rfps_list)} total RFP entries to {JSON_PATH}")


if __name__ == "__main__":
    main()
