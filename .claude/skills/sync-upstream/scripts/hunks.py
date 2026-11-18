#!/usr/bin/env python3
"""Show or resolve the conflict hunks of one file.

    hunks.py show FILE            print each hunk, numbered, ours then theirs
    hunks.py pick FILE c0 c1 ...  resolve hunk i with ci: o (ours), t (theirs), ot / to (both, in order), x (neither)

For a hunk that needs an edit (translate upstream's new text, merge two calls), resolve it with a small script or the
editor instead; pick is for hunks where one side, or both verbatim, is right.
"""
import re
import sys

H = re.compile(r'<<<<<<< [^\n]*\n(.*?)(?:\|\|\|\|\|\|\| [^\n]*\n.*?)?=======\n(.*?)>>>>>>> [^\n]*\n', re.DOTALL)
cmd, path, *choices = sys.argv[1:]
s = open(path).read()
hs = H.findall(s)
if cmd == "show":
    for i, (o, t) in enumerate(hs):
        print(f"######## HUNK {i} — OURS\n{o}######## HUNK {i} — THEIRS\n{t}")
    sys.exit(0)
assert len(choices) == len(hs), f"{len(hs)} hunks, {len(choices)} choices"
it = iter(choices)


def rep(m):
    c = next(it)
    o, t = m.group(1), m.group(2)
    return {"o": o, "t": t, "ot": o + t, "to": t + o, "x": ""}[c]


open(path, "w").write(H.sub(rep, s))
print(f"resolved {len(hs)} hunks in {path}")
