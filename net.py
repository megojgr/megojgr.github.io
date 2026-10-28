"""Kleiner HTTP-Helfer: gleicher User-Agent überall, ein Wiederholungsversuch bei Aussetzern."""
import time
import urllib.request

UA = "Mozilla/5.0 (private-news-reader)"


def fetch(url, timeout=20, retries=1):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2)
    raise last
