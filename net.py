"""Kleiner HTTP-Helfer: gleicher User-Agent überall, ein Wiederholungsversuch bei Aussetzern."""
import time
import urllib.request

UA = "Mozilla/5.0 (private-news-reader)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def fetch(url, timeout=20, retries=1, headers=None, ua=None):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua or UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2)
    raise last
