#!/usr/bin/env python3
"""Render a command's colored terminal output as an SVG "terminal window" for the docs.

  tools/terminal-svg.py OUT.svg "musesh help" [--title TEXT] [--lines A:B] [--width COLS]

The command runs in a pseudo-terminal (so it prints its real colors); ANSI styles are
mapped onto a small palette. Re-run after changing output to refresh docs/images/.
"""

import argparse
import html
import os
import pty
import re

PALETTE = {
    "fg": "#d4d7de", "dim": "#6c7280", "magenta": "#d783e8", "cyan": "#6fc8d6",
    "green": "#8fd18a", "yellow": "#e6c07b", "red": "#ef7b7b", "bg": "#16171d", "bar": "#22242c",
}
SGR = re.compile(r"\x1b\[([0-9;]*)m")
CHAR_W, LINE_H, FONT = 8.1, 19, 13  # CHAR_W leaves headroom for wider fallback fonts


def capture(command, width):
    """Run command on its own pseudo-terminal (so it prints colors) and collect the output.
    Unlike `script`, this doesn't depend on stdin, so it works from scripts and pipelines."""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(COLUMNS=str(width), TERM="xterm-256color")
        os.execvp("sh", ["sh", "-c", command])
    chunks = []
    while True:
        try:
            data = os.read(fd, 65536)
        except OSError:  # child closed the terminal
            break
        if not data:
            break
        chunks.append(data)
    os.waitpid(pid, 0)
    out = b"".join(chunks).decode(errors="replace")
    out = out.replace("\r", "")
    out = re.sub(r"\x1b\[\?[0-9;]*[a-zA-Z]", "", out)  # cursor modes etc.
    return out.rstrip("\n").split("\n")


def spans(line):
    """Split one line into (text, style) runs following the SGR codes."""
    style, pos, runs = {"bold": False, "dim": False, "color": None}, 0, []
    for m in SGR.finditer(line):
        if m.start() > pos:
            runs.append((line[pos:m.start()], dict(style)))
        for code in (m.group(1) or "0").split(";"):
            code = int(code or 0)
            if code == 0:
                style = {"bold": False, "dim": False, "color": None}
            elif code == 1:
                style["bold"] = True
            elif code == 2:
                style["dim"] = True
            elif code in (31, 32, 33, 35, 36):
                style["color"] = {31: "red", 32: "green", 33: "yellow", 35: "magenta", 36: "cyan"}[code]
        pos = m.end()
    runs.append((line[pos:], dict(style)))
    return [(t, s) for t, s in runs if t]


def render(lines, title):
    cols = max((len(SGR.sub("", l)) for l in lines), default=40)
    pad_x, top = 22, 46
    w = int(cols * CHAR_W + pad_x * 2)
    h = int(top + len(lines) * LINE_H + 22)
    p = PALETTE
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
           f'<rect width="{w}" height="{h}" rx="10" fill="{p["bg"]}"/>',
           f'<path d="M0 10a10 10 0 0 1 10-10h{w - 20}a10 10 0 0 1 10 10v18H0z" fill="{p["bar"]}"/>']
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(f'<circle cx="{20 + i * 18}" cy="14" r="5.5" fill="{c}"/>')
    out.append(f'<text x="{w / 2}" y="18.5" text-anchor="middle" fill="{p["dim"]}" '
               f'font-family="-apple-system,Segoe UI,Helvetica,sans-serif" font-size="12">{html.escape(title)}</text>')
    out.append(f'<g font-family="SF Mono,Menlo,Consolas,monospace" font-size="{FONT}" xml:space="preserve">')
    for i, line in enumerate(lines):
        y = top + i * LINE_H
        parts = []
        for text, s in spans(line):
            fill = p[s["color"]] if s["color"] else (p["dim"] if s["dim"] else p["fg"])
            attrs = f'fill="{fill}"' + (' font-weight="700"' if s["bold"] else "")
            if s["dim"] and s["color"]:
                attrs += ' opacity="0.7"'
            # Non-breaking spaces: SVG renderers collapse runs of normal spaces, which kills alignment.
            parts.append(f"<tspan {attrs}>{html.escape(text).replace(' ', '&#160;')}</tspan>")
        out.append(f'<text x="{pad_x}" y="{y}">{"".join(parts)}</text>')
    out += ["</g>", "</svg>"]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("command")
    ap.add_argument("--title", default="")
    ap.add_argument("--lines", help="keep only lines A:B (Python slice)")
    ap.add_argument("--width", type=int, default=120)
    ap.add_argument("--prompt", action="store_true", help="show '$ command' as the first line")
    a = ap.parse_args()
    lines = capture(a.command, a.width)
    if a.lines:
        start, _, end = a.lines.partition(":")
        lines = lines[int(start or 0):int(end) if end else None]
    if a.prompt:
        lines = [f"\x1b[35m$\x1b[0m {a.command}"] + lines
    with open(a.out, "w") as f:
        f.write(render(lines, a.title or a.command))


if __name__ == "__main__":
    main()
