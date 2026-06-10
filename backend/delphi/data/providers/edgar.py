"""Recent SEC filings via EDGAR's free JSON API.

Two hops: company_tickers.json maps ticker -> CIK (cached at module
level), then data.sec.gov/submissions/CIK##########.json lists recent
filings. We keep 10-K/10-Q/8-K and return the fixture ``filings`` shape
with snippets set to {} (no document parsing over the network). Returns
None on any failure.
"""

from __future__ import annotations

from .base import FilingsProvider

USER_AGENT = "DELPHI Research delphi@example.com"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

KEEP_FORMS = {"10-K", "10-Q", "8-K"}
MAX_FILINGS = 6

_ticker_to_cik: dict[str, int] | None = None  # process-lifetime cache


class EdgarFilings(FilingsProvider):
    name = "edgar_filings"

    def fetch(self, ticker: str) -> dict | None:
        try:
            import httpx

            cik = self._resolve_cik(ticker)
            if cik is None:
                return None

            resp = httpx.get(
                SUBMISSIONS_URL.format(cik=cik),
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
                follow_redirects=True,
            )
            resp.raise_for_status()
            recent = resp.json().get("filings", {}).get("recent", {})

            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])

            filings = []
            for form, date, accession, doc in zip(forms, dates, accessions, docs):
                if form not in KEEP_FORMS:
                    continue
                acc_nodash = accession.replace("-", "")
                url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{acc_nodash}/{doc}"
                    if doc
                    else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                    f"&CIK={cik:010d}&type={form}&dateb=&owner=include&count=10"
                )
                filings.append(
                    {
                        "doc_type": form,
                        "title": f"{form} filed {date}",
                        "date": date,
                        "url": url,
                        "snippets": {},
                    }
                )
                if len(filings) >= MAX_FILINGS:
                    break

            return {"filings": filings} if filings else None
        except Exception:
            return None

    @staticmethod
    def _resolve_cik(ticker: str) -> int | None:
        global _ticker_to_cik
        try:
            if _ticker_to_cik is None:
                import httpx

                resp = httpx.get(
                    TICKER_MAP_URL,
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                _ticker_to_cik = {
                    entry["ticker"].upper(): int(entry["cik_str"])
                    for entry in resp.json().values()
                }
            return _ticker_to_cik.get(ticker.upper())
        except Exception:
            return None
