import concurrent.futures
import json
import os
import random
import re
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'


def fetch_json(url, timeout=5):
    last_error = None
    targets = [
        url,
        'https://corsproxy.io/?url=' + urllib.parse.quote(url, safe=''),
        'https://api.codetabs.com/v1/proxy?quest=' + urllib.parse.quote(url, safe='')
    ]
    for target in targets:
        try:
            req = urllib.request.Request(target, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8', 'replace'))
        except Exception as e:
            last_error = e
    raise RuntimeError('upstream failed: ' + str(last_error))


def parallel_first(jobs, timeout=12):
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs))
    try:
        futures = [ex.submit(job) for job in jobs]
        for f in concurrent.futures.as_completed(futures, timeout=timeout):
            try:
                value = f.result()
                if value:
                    return value
            except Exception:
                pass
        return None
    except (concurrent.futures.TimeoutError, TimeoutError):
        return None
    finally:
        ex.shutdown(wait=False)


def translate(text):
    encoded = urllib.parse.quote(text, safe='')

    def lingva(host):
        def job():
            data = fetch_json('https://' + host + '/api/v1/en/tr/' + encoded)
            t = str((data or {}).get('translation') or '').strip()
            return t or None
        return job

    def google():
        data = fetch_json('https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=tr&q=' + encoded)
        t = ''
        if isinstance(data, list) and data:
            if isinstance(data[0], str):
                t = data[0].strip()
            elif isinstance(data[0], list) and data[0] and isinstance(data[0][0], str):
                t = data[0][0].strip()
        elif isinstance(data, dict) and isinstance(data.get('sentences'), list) and data['sentences']:
            t = str(data['sentences'][0].get('trans') or '').strip()
        return t or None

    def mymemory():
        data = fetch_json('https://api.mymemory.translated.net/get?q=' + encoded + '&langpair=en%7Ctr')
        t = ''
        if isinstance(data, dict) and isinstance(data.get('responseData'), dict):
            t = str(data['responseData'].get('translatedText') or '').strip()
        if t and 'MYMEMORY WARNING' not in t.upper():
            return t
        return None

    return parallel_first([google, lingva('lingva.ml'), lingva('lingva.lunar.icu'), mymemory], timeout=10) or ''


def word_pattern(word):
    return re.compile(r'\b' + re.escape(word.lower()) + r'(?:s|es|ed|d|ing|ly|er|est|ness|ment|ion|ions|ive|ives)?\b', re.I)


def dictionary_example(word):
    data = fetch_json('https://api.dictionaryapi.dev/api/v2/entries/en/' + urllib.parse.quote(word.lower(), safe=''))
    exs = []
    if isinstance(data, list):
        for entry in data:
            for meaning in entry.get('meanings') or []:
                for d in meaning.get('definitions') or []:
                    if d.get('example'):
                        exs.append(str(d['example']).strip())
    pat = word_pattern(word)
    usable = [x for x in exs if pat.search(x)]
    if not usable:
        return None
    text = random.choice(usable)
    tr = translate(text)
    if not tr:
        return None
    return {'keyword': word, 'text': text, 'translation': tr}


def tatoeba_example(word):
    data = fetch_json('https://tatoeba.org/en/api_v0/search?from=eng&to=tur&query=' + urllib.parse.quote(word, safe=''))
    pat = word_pattern(word)
    pairs = []
    results = data.get('results') or [] if isinstance(data, dict) else []
    for r in results:
        text = str(r.get('text') or '').strip()
        if not text or not pat.search(text):
            continue
        tr = ''
        for group in r.get('translations') or []:
            if isinstance(group, list):
                hit = next((t for t in group if isinstance(t, dict) and t.get('lang') == 'tur' and t.get('text')), None)
                if hit:
                    tr = str(hit['text']).strip()
                    break
        if tr:
            pairs.append({'keyword': word, 'text': text, 'translation': tr})
    return random.choice(pairs) if pairs else None


def build_example(word):
    return parallel_first([
        lambda: dictionary_example(word),
        lambda: tatoeba_example(word)
    ], timeout=18)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/ping':
            self.reply({'ok': True})
            return
        if parsed.path == '/api/example':
            params = urllib.parse.parse_qs(parsed.query)
            word = (params.get('word') or [''])[0].strip()
            if not word:
                self.reply({'error': 'word required'}, 400)
                return
            try:
                pair = build_example(word)
            except Exception:
                pair = None
            if pair:
                self.reply(pair)
            else:
                self.reply({'error': 'not found'}, 404)
            return
        super().do_GET()

    def reply(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    server = None
    port = None
    for p in range(8787, 8792):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', p), Handler)
            port = p
            break
        except OSError:
            continue
    if not server:
        print('Bos port bulunamadi (8787-8791)')
        return
    url = 'http://127.0.0.1:' + str(port)
    print('Kozmik Kartlar calisiyor: ' + url)
    print('Kapatmak icin Ctrl+C')
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nKapatildi')


if __name__ == '__main__':
    main()
