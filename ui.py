"""Shared terminal styling for musesh and its helper scripts.

Colors switch off when output isn't a terminal or NO_COLOR is set.
"""

import os
import sys
from pathlib import Path

HOME = Path.home()
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _style(code):
    return (lambda s: f"\033[{code}m{s}\033[0m") if COLOR else (lambda s: str(s))


bold, dim, italic = _style("1"), _style("2"), _style("3")
accent, accent_bold = _style("35"), _style("1;35")  # magenta, like the shell prompt
green, yellow, red, cyan, blue = _style("32"), _style("33"), _style("31"), _style("36"), _style("34")


def tilde(path):
    return str(path).replace(str(HOME), "~", 1)


def heading(text):
    print(f"\n{accent_bold('::')} {bold(text)}")


def ok(text):
    print(f"{green('✓')} {text}")


def warn(text):
    print(f"{yellow('!')} {text}")


def note(text):
    print(f"  {dim(text)}")


def die(text):
    print(f"{red('✗')} {text}", file=sys.stderr)
    sys.exit(1)


def summary(rows, indent=2):
    """Aligned 'key  value' block."""
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{' ' * indent}{dim(k.ljust(width))}  {v}")
