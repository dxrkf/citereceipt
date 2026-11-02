import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
import citereceipt as c

DOI = '10.1038/nphys1170'
def record():
    return {'status': 'found', 'titles': ['Measured measurement'], 'publication_years': [2009]}
def payload(**values):
    return {'message': {'DOI': DOI, 'title': ['Measured measurement'], 'published': {'date-parts': [[2009]]}, **values}}
def opener(data):
    return lambda *args, **kw: io.BytesIO(json.dumps(data).encode())

class Tests(unittest.TestCase):
    def test_doi_forms(self):
        for doi in [DOI, ' DOI:10.1038/NPHYS1170 ', 'https://doi.org/10.1038%2Fnphys1170']:
            self.assertEqual(c.normalize_doi(doi), DOI)
    def test_invalid_doi(self):
        for doi in [None, 'https://evil.test/'+DOI, '10.123/a b', 'https://doi.org/'+DOI+'?key=secret', DOI+'\nX']:
            with self.subTest(doi=doi), self.assertRaises(ValueError):c.normalize_doi(doi)
    def test_unicode_and_markup_title(self):
        self.assertEqual(c.normalized_title('ＦＯＯ: <i>Bar</i> &amp; BAZ!'), 'foo bar baz')
    def test_matching_fields(self):
        r=c.audit([{'doi':DOI,'title':'MEASURED: measurement','year':2009}],lambda _:record())
        self.assertEqual(r['rows_with_issues'],0)
    def test_mismatching_fields(self):
        r=c.audit([{'doi':DOI,'title':'Invented demo title','year':2025}],lambda _:record())
        self.assertEqual(r['results'][0]['issues'],['title_differs','year_differs'])
    def test_duplicate_fetch_once(self):
        calls=[]
        r=c.audit([{'doi':DOI}]*3,lambda d:(calls.append(d) or record()))
        self.assertEqual(len(calls),1);self.assertEqual(r['results'][2]['duplicate_of'],1)
    def test_missing_metadata(self):
        r=c.audit([{'doi':DOI,'title':'Some title','year':2009}],lambda _:dict(status='found',titles=[],publication_years=[]))
        self.assertEqual(r['results'][0]['issues'],['title_unavailable','year_unavailable'])
    def test_stops_after_error_but_reuses_cache(self):
        calls=[]
        def fetch(d):calls.append(d);return record() if d==DOI else {'status':'error','detail':'429'}
        r=c.audit([{'doi':d} for d in [DOI,'10.1234/a','10.1234/b',DOI]],fetch,sleep=lambda _:None)
        self.assertEqual(calls,[DOI,'10.1234/a']);self.assertTrue(r['incomplete'])
        self.assertEqual(r['results'][2]['status'],'not_checked');self.assertEqual(r['results'][3]['status'],'found')
    def test_serial_pacing(self):
        delays=[];c.audit([{'doi':DOI},{'doi':'10.1234/a'}],lambda _:record(),sleep=delays.append)
        self.assertEqual(delays,[1.0])
    def test_request_encodes_doi_to_fixed_host(self):
        def fake(req,timeout):
            self.assertEqual(req.full_url,'https://api.crossref.org/works/10.1038%2Fnphys1170')
            self.assertEqual(timeout,25);return io.BytesIO(json.dumps(payload()).encode())
        self.assertEqual(c.lookup(DOI,opener=fake)['status'],'found')
    def test_publication_year_variants(self):
        r=c.lookup(DOI,opener=opener(payload(**{'published-online':{'date-parts':[[2008]]},'published-print':{'date-parts':[[2009]]}})))
        self.assertEqual(r['publication_years'],[2008,2009])
    def test_wrong_doi_record(self):self.assertEqual(c.lookup(DOI,opener=opener(payload(DOI='10.1234/other')))['status'],'error')
    def test_malformed_payload(self):
        for data in [[],{'message':[]},payload(title=[22])]:self.assertEqual(c.lookup(DOI,opener=opener(data))['status'],'error')
    def test_http_404_is_not_invalid_claim(self):
        def fail(*a,**k):raise urllib.error.HTTPError('url',404,'missing',{},None)
        r=c.lookup(DOI,opener=fail);self.assertEqual(r['status'],'not_found');self.assertIn('does not prove',r['detail'])
    def test_rate_limit_and_network_failure(self):
        for error in [urllib.error.HTTPError('url',429,'limit',{},None),urllib.error.URLError('offline')]:
            def fail(*a,**k):raise error
            self.assertEqual(c.lookup(DOI,opener=fail)['status'],'error')
    def test_response_size_cap(self):self.assertEqual(c.lookup(DOI,opener=lambda *a,**k:io.BytesIO(b'x'*(c.MAX_BYTES+1)))['status'],'error')
    def test_input_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.json'
            for value in [[],[{'doi':DOI,'year':True}],[{'doi':DOI,'title':''}],[{'doi':DOI,'secret':'x'}],[{'doi':DOI}]*101]:
                p.write_text(json.dumps(value))
                with self.assertRaises(ValueError):c.load_entries(p)
            p.write_text(json.dumps([{'doi':'DOI:'+DOI,'year':2009}]))
            self.assertEqual(c.load_entries(p)[0]['doi'],DOI)
    def test_html_escapes_untrusted_titles(self):
        r=c.audit([{'doi':DOI}],lambda _:{'status':'found','titles':['<script>bad</script>'],'publication_years':[]})
        doc=c.render_html(r);self.assertNotIn('<script>',doc);self.assertIn('&lt;script&gt;',doc)
    def test_atomic_output_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out';c.atomic_write(p,'old');c.atomic_write(p,'new');self.assertEqual(p.read_text(),'new')
            s=Path(d)/'link';s.symlink_to(p)
            with self.assertRaises(ValueError):c.atomic_write(s,'bad')
            self.assertEqual(p.read_text(),'new')

if __name__=='__main__':unittest.main()
