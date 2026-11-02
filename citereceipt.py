#!/usr/bin/env python3
"""Compare a DOI bibliography with live Crossref metadata (Python 3.10+)."""
import argparse
import html
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

MAX_BYTES = 2_000_000


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = TextOnly()
    parser.feed(value)
    return ''.join(parser.parts).strip()


def normalized_title(value):
    value = unicodedata.normalize('NFKC', plain(value)).casefold()
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in value).split())


def normalize_doi(value):
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError('DOI must be a string of at most 1000 characters')
    value = value.strip()
    if value.lower().startswith(('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/')):
        url = urllib.parse.urlsplit(value)
        if url.query or url.fragment:
            raise ValueError('DOI URL must not contain query or fragment')
        value = urllib.parse.unquote(url.path[1:])
    elif value.lower().startswith('doi:'):
        value = value[4:].strip()
    if not re.fullmatch(r'10\.\d{4,9}/[^\s\x00-\x1f\x7f]+', value, re.ASCII):
        raise ValueError('unsupported DOI syntax; use a bare DOI or doi.org URL')
    return value.lower()


def load_entries(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('input exceeds 2 MB')
    entries = json.loads(raw)
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError('input must be a JSON array of 1 to 100 references')
    cleaned = []
    for item in entries:
        if not isinstance(item, dict) or set(item) - {'doi', 'title', 'year'}:
            raise ValueError('each entry accepts only doi, title and year')
        doi = normalize_doi(item.get('doi'))
        if 'title' in item and (not isinstance(item['title'], str) or not normalized_title(item['title']) or len(item['title']) > 2000):
            raise ValueError('title must be nonempty text of at most 2000 characters')
        if 'year' in item and (type(item['year']) is not int or not 1000 <= item['year'] <= 9999):
            raise ValueError('year must be an integer between 1000 and 9999')
        cleaned.append(dict(item, doi=doi))
    return cleaned


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def lookup(doi, timeout=25, opener=None):
    """Return bounded metadata only. Never follow DOI or publisher URLs."""
    url = 'https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='')
    request = urllib.request.Request(url, headers={'User-Agent': 'CiteReceipt/1.0', 'Accept': 'application/json'})
    open_request = opener or urllib.request.build_opener(NoRedirect()).open
    try:
        with open_request(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('API response exceeds 2 MB')
        payload = json.loads(raw)
        message = payload.get('message') if isinstance(payload, dict) else None
        if not isinstance(message, dict) or normalize_doi(message.get('DOI')) != doi:
            raise ValueError('API returned an unexpected DOI record')
        titles = message.get('title', [])
        if not isinstance(titles, list) or any(not isinstance(t, str) for t in titles):
            raise ValueError('invalid title metadata')
        years = set()
        for field in ('published', 'published-online', 'published-print'):
            date = message.get(field, {})
            parts = date.get('date-parts', []) if isinstance(date, dict) else []
            if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                year = parts[0][0]
                if type(year) is int and 1000 <= year <= 9999:
                    years.add(year)
        return {'status': 'found', 'titles': [plain(t) for t in titles], 'publication_years': sorted(years), 'record_url': url}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {'status': 'not_found', 'detail': 'Not found in Crossref; this does not prove the DOI is invalid.'}
        return {'status': 'error', 'detail': f'Crossref HTTP {exc.code}; remaining unique requests stopped. Retry later; no automatic retries.'}
    except (urllib.error.URLError, OSError, ValueError, TypeError, OverflowError):
        return {'status': 'error', 'detail': 'Network failure or malformed metadata; remaining unique requests stopped.'}


def audit(entries, fetcher=lookup, delay=1.0, sleep=time.sleep):
    cache = {}
    first_seen = {}
    results = []
    stopped = False
    for index, entry in enumerate(entries, 1):
        doi = entry['doi']
        duplicate_of = first_seen.get(doi)
        if doi not in cache:
            if stopped:
                cache[doi] = {'status': 'not_checked', 'detail': 'Skipped after an earlier provider/network failure.'}
            else:
                if cache:
                    sleep(delay)
                cache[doi] = fetcher(doi)
                stopped = cache[doi]['status'] == 'error'
            first_seen[doi] = index
        record = cache[doi]
        issues = []
        if duplicate_of is not None:
            issues.append('duplicate_doi')
        if record['status'] == 'found':
            if 'title' in entry:
                if not record['titles']:
                    issues.append('title_unavailable')
                elif normalized_title(entry['title']) not in [normalized_title(t) for t in record['titles']]:
                    issues.append('title_differs')
            if 'year' in entry:
                if not record['publication_years']:
                    issues.append('year_unavailable')
                elif entry['year'] not in record['publication_years']:
                    issues.append('year_differs')
        else:
            issues.append(record['status'])
        results.append({'reference': index, 'input': entry, 'duplicate_of': duplicate_of, **record, 'issues': issues})
    return {'format': 'citereceipt-v1', 'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'source': 'Crossref REST API', 'unique_dois': len(cache), 'rows_with_issues': sum(bool(r['issues']) for r in results), 'incomplete': stopped, 'results': results}


def render_html(report):
    def esc(value):
        return html.escape(str(value))
    rows = []
    for row in report['results']:
        values = [row['reference'], row['input']['doi'], row['status'], '; '.join(row.get('titles', [])), ', '.join(map(str, row.get('publication_years', []))), ', '.join(row['issues']) or 'no listed discrepancy']
        rows.append('<tr>' + ''.join('<td>' + esc(v) + '</td>' for v in values) + '</tr>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>CiteReceipt</title><style>body{font:17px system-ui;background:#111827;color:#e5e7eb;margin:40px}h1,a{color:#a5b4fc}td,th{padding:14px;text-align:left;border-bottom:1px solid #475569}table{border-collapse:collapse;width:100%}.scroll{overflow-x:auto}</style><h1>CiteReceipt</h1><p>Checked: ''' + esc(report['checked_at_utc']) + '</p><p>Rows with issues: ' + str(report['rows_with_issues']) + ' · Incomplete: ' + str(report['incomplete']) + '</p><p>Metadata comparison only. No listed discrepancy does not verify scientific quality, claims or retraction status.</p><div class="scroll"><table><tr><th>#</th><th>DOI</th><th>Lookup</th><th>Crossref title</th><th>Publication years</th><th>Issues</th></tr>' + ''.join(rows) + '</table></div><p>Metadata source: <a href="https://www.crossref.org/">Crossref</a>. Re-run to refresh. Submitted titles and years remain local.</p></html>'


def atomic_write(path, text):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('output symlinks are refused')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='JSON array of doi and optional title/year')
    parser.add_argument('--html', help='write a static HTML receipt')
    parser.add_argument('--json', action='store_true', help='print the full JSON receipt')
    parser.add_argument('--timeout', type=int, default=25, choices=range(1, 61), metavar='1..60')
    args = parser.parse_args()
    try:
        entries = load_entries(args.input)
        if args.html and Path(args.html).resolve() == Path(args.input).resolve():
            raise ValueError('input and HTML output must differ')
        report = audit(entries, fetcher=lambda doi: lookup(doi, args.timeout))
        if args.html:
            atomic_write(args.html, render_html(report))
        if args.json:
            print(json.dumps(report, ensure_ascii=True, indent=2))
        else:
            print(f"CiteReceipt: {len(entries)} references, {report['unique_dois']} unique DOIs, {report['rows_with_issues']} rows with issues")
            for row in report['results']:
                print(f"#{row['reference']} {row['input']['doi']} | {row['status']} | " + (', '.join(row['issues']) or 'no listed discrepancy'))
            print('Metadata comparison only; scientific claims and retraction status are not checked.')
        return 2 if report['incomplete'] else int(report['rows_with_issues'] > 0)
    except (OSError, ValueError, TypeError):
        print('error: invalid input or output path; no complete receipt produced', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
