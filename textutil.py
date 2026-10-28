"""Stichwort-Suche: Wörter mit "$" am Ende müssen ganze Wörter sein, alle anderen gelten als Wortanfang."""
import re


def compile_keywords(words):
    pats = []
    for w in words:
        if w.endswith("$"):
            pats.append(re.compile(r"\b" + re.escape(w[:-1]) + r"\b", re.I))
        else:
            pats.append(re.compile(r"\b" + re.escape(w), re.I))
    return pats


def count_hits(pats, title, summary):
    return sum(2 for p in pats if p.search(title)) + sum(1 for p in pats if p.search(summary))
