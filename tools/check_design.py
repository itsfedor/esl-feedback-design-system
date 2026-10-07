#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_design.py — static design-system conformance linter.

Usage:
    python3 check_design.py <file.html> [--tokens ../tokens.json]

Checks (one PASS/FAIL line each; exit code 0 if everything passes, else 1):

  structural (always run):
    1. HTML tag balance (void-aware)
    2. design-system version stamp: <!-- design-system: vX.Y -->
    3. required components: legend + >=1 fix item (homework-analysis skeleton;
       closing block optional since v1.1) or band-hero + skill-card
       (band-card skeleton, v1.3)
    4. no inline style="..." attributes
    5. @media print present
    6. :focus / :focus-visible present
    7. distinct CSS font sizes <= 7

  token-based (need tokens.json, read at RUN time):
    8. CSS font-size values subset of tokens' font_sizes
    9. CSS hex colors subset of tokens' colors.allowed

If tokens.json is missing (or unreadable): prints
"spec not found — token checks skipped" and still runs the structural
checks; exit 1 only on structural failures.

Python stdlib only.
"""
from __future__ import annotations

import argparse
import html.parser
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# Constants / configuration
# --------------------------------------------------------------------------

VOID_ELEMENTS = {
    "area", "base", "basefont", "br", "col", "embed", "frame", "hr", "img",
    "input", "isindex", "keygen", "link", "meta", "param", "source", "track",
    "wbr",
}

STAMP_RE = re.compile(r"<!--\s*design-system\s*:\s*(v?\d+(?:\.\d+)*)\s*-->", re.I)
STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
INLINE_STYLE_RE = re.compile(r"<[a-zA-Z][^<>]*?\sstyle\s*=\s*([\"'])(.*?)\1", re.S)
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;}{]+)", re.I)
LENGTH_RE = re.compile(r"(-?\d*\.?\d+)\s*(rem|em|px|pt|%)\b", re.I)
HEX_RE = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
URL_FN_RE = re.compile(r"url\([^)]*\)", re.I)
CUSTOM_PROP_RE = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;}{]+)")
VAR_RE = re.compile(r"var\(\s*--([A-Za-z0-9_-]+)\s*(?:,\s*([^()]*?))?\s*\)")

# Required-component markers (class-token based; documented in tools/README.md)
CLASS_ATTR_RE = re.compile(r"class\s*=\s*[\"']([^\"']*)[\"']", re.I)


def class_tokens(source: str) -> list[str]:
    toks: list[str] = []
    for m in CLASS_ATTR_RE.finditer(source):
        toks += m.group(1).split()
    return toks


def is_legend_container(tok: str) -> bool:
    return tok == "legend"


def is_fix_item(tok: str) -> bool:
    return tok == "fix" or tok.startswith("fix-")


def is_skill_card(tok: str) -> bool:
    return tok == "skill-card"


def is_closing(tok: str) -> bool:
    return tok == "closing" or tok.startswith("closing")


MAX_DISTINCT_FONT_SIZES = 7
DEFAULT_TOKENS = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tokens.json"))

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def norm_size(value: str) -> str:
    """Normalize a simple CSS length to rem-based form for comparison."""
    v = value.strip().lower()
    m = re.fullmatch(r"(-?\d*\.?\d+)\s*(rem|em|px|pt|%)", v)
    if not m:
        return v
    num, unit = float(m.group(1)), m.group(2)
    if unit == "px":
        num, unit = num / 16.0, "rem"
    elif unit == "pt":
        num, unit = num / 12.0, "rem"
    elif unit == "em":
        unit = "rem"  # feedback docs scale off the root; treated as equivalent
    out = ("%.4f" % num).rstrip("0").rstrip(".")
    return f"{out}{unit}"


def norm_hex(value: str) -> str:
    h = value.strip().lower().lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    return "#" + h


def size_tokens(value: str) -> list[str]:
    """All normalized simple lengths inside a font-size value (clamp()-aware)."""
    found = LENGTH_RE.findall(value)
    if not found:
        return [norm_size(value)]
    return [norm_size(f"{n}{u}") for n, u in found]


def css_variables(css: str) -> dict:
    """`--name: value` definitions from the stylesheet (design tokens live here)."""
    return {m.group(1): m.group(2).strip() for m in CUSTOM_PROP_RE.finditer(css)}


def resolve_vars(value: str, var_map: dict, _depth: int = 0) -> str:
    """Resolve var(--x[, fallback]) through the file's own custom-property map."""
    if _depth > 6 or "var(" not in value:
        return value

    def repl(m):
        name, fallback = m.group(1), m.group(2)
        if name in var_map:
            return resolve_vars(var_map[name], var_map, _depth + 1)
        return fallback.strip() if fallback else m.group(0)

    return VAR_RE.sub(repl, value)


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------


class TagBalance(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int, int]] = []  # tag, line, offset
        self.errors: list[str] = []
        self.opens = 0

    def _pos(self) -> tuple[int, int]:
        return self.getpos()

    def handle_starttag(self, tag, attrs):  # noqa: D102
        if tag in VOID_ELEMENTS:
            return
        self.opens += 1
        self.stack.append((tag, self._pos()[0], self._pos()[1]))

    def handle_startendtag(self, tag, attrs):  # self-closing <tag/> — fine
        return

    def handle_endtag(self, tag):  # noqa: D102
        if tag in VOID_ELEMENTS:
            return
        ln = self._pos()[0]
        if not self.stack:
            self.errors.append(f"line {ln}: unexpected </{tag}> (nothing open)")
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        idx = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag),
            None,
        )
        if idx is None:
            self.errors.append(f"line {ln}: </{tag}> without matching open tag")
            return
        left_open = ", ".join(f"<{t}> (line {l})" for t, l, _ in self.stack[idx + 1:])
        self.errors.append(
            f"line {ln}: </{tag}> while still open: {left_open}"
        )
        del self.stack[idx:]

    def unclosed(self) -> list[str]:
        return [f"<{t}> (line {l})" for t, l, _ in self.stack]


def extract_css(source: str) -> str:
    return "\n".join(m.group(1) for m in STYLE_BLOCK_RE.finditer(source))


def extract_inline_styles(source: str) -> list[tuple[int, str]]:
    """[(line, style-attribute-value), ...]"""
    out = []
    for m in INLINE_STYLE_RE.finditer(source):
        out.append((line_of(source, m.start()), m.group(2)))
    return out


def font_size_values(css: str, inline_styles: list[tuple[int, str]], var_map: dict):
    """-> [(effective_value, origin_description), ...]; var(--x) resolved."""
    out: list[tuple[str, str]] = []
    for m in FONT_SIZE_RE.finditer(URL_FN_RE.sub("", css)):
        raw = m.group(1).strip()
        res = resolve_vars(raw, var_map)
        out.append((res, f"css ({raw})" if res != raw else "css"))
    for ln, val in inline_styles:
        for m in FONT_SIZE_RE.finditer(val):
            raw = m.group(1).strip()
            res = resolve_vars(raw, var_map)
            origin = f"inline style line {ln}" + (f" ({raw})" if res != raw else "")
            out.append((res, origin))
    return out


def hex_colors(css: str, inline_styles: list[tuple[int, str]]):
    out: list[tuple[str, str]] = []
    for m in HEX_RE.finditer(URL_FN_RE.sub("", css)):
        out.append((m.group(0), "css"))
    for ln, val in inline_styles:
        for m in HEX_RE.finditer(URL_FN_RE.sub("", val)):
            out.append((m.group(0), f"inline style line {ln}"))
    return out


# --------------------------------------------------------------------------
# tokens.json loading (tolerant about shapes; read at run time)
# --------------------------------------------------------------------------


def _collect_strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, (int, float)):
        return [f"{node}rem"]
    if isinstance(node, list):
        out = []
        for item in node:
            out += _collect_strings(item)
        return out
    if isinstance(node, dict):
        out = []
        for key, val in node.items():
            # skip obviously non-value keys
            if isinstance(val, (dict, list, str, int, float)) and not str(key).startswith("_"):
                out += _collect_strings(val)
        return out
    return []


def _find_key(node, names: tuple[str, ...]):
    """Search a dict (depth-first, any nesting) for one of the given keys."""
    if isinstance(node, dict):
        for name in names:
            if name in node:
                return node[name]
        for val in node.values():
            found = _find_key(val, names)
            if found is not None:
                return found
    return None


def load_token_sets(tokens_path: str):
    """-> (font_size_set | None, color_set | None, meta dict)."""
    with open(tokens_path, "r", encoding="utf-8") as fh:
        tok = json.load(fh)

    raw_sizes = _find_key(
        tok, ("font_sizes", "fontSizes", "font_size", "type_scale", "typeScale", "scale")
    )
    font_sizes = None
    if raw_sizes is not None:
        font_sizes = set()
        for s in _collect_strings(raw_sizes):
            m = re.fullmatch(r"(-?\d*\.?\d+)\s*(rem|em|px|pt|%)?", s.strip().lower())
            if m:
                unit = m.group(2) or "rem"
                font_sizes.add(norm_size(f"{m.group(1)}{unit}"))
            else:
                font_sizes.add(s.strip().lower())
        if not font_sizes:
            font_sizes = None

    colors_node = _find_key(tok, ("colors", "palette", "allowed_colors"))
    color_set = None
    if colors_node is not None:
        if isinstance(colors_node, dict) and "allowed" in colors_node:
            colors_node = colors_node["allowed"]
        strings = _collect_strings(colors_node)
        color_set = {norm_hex(s) for s in strings if re.fullmatch(r"#[0-9a-fA-F]{3,8}", s.strip())}
        if not color_set:
            color_set = None

    meta = {
        "version": tok.get("version") if isinstance(tok, dict) else None,
        "name": tok.get("name") if isinstance(tok, dict) else None,
    }
    return font_sizes, color_set, meta


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Static design-system conformance linter (stdlib only)."
    )
    ap.add_argument("html_file")
    ap.add_argument("--tokens", default=DEFAULT_TOKENS, help="path to tokens.json")
    args = ap.parse_args()

    path = args.html_file
    if not os.path.isfile(path):
        print(f"error: file not found: {path}")
        return 2

    source = open(path, "r", encoding="utf-8").read()
    css = extract_css(source)
    var_map = css_variables(css)
    inline_styles = extract_inline_styles(source)
    sizes = font_size_values(css, inline_styles, var_map)
    colors = hex_colors(css, inline_styles)

    print(f"== design check == {path}")

    results: list[tuple[str, str]] = []  # (PASS/FAIL/SKIP, label)
    notes: list[str] = []

    # -- 1. tag balance -----------------------------------------------------
    parser = TagBalance()
    parser.feed(source)
    parser.close()
    balance_errors = parser.errors + [
        f"unclosed at EOF: {u}" for u in parser.unclosed()
    ]
    if balance_errors:
        results.append(("FAIL", f"tag balance ({len(balance_errors)} problem(s))"))
        notes += ["    " + e for e in balance_errors[:10]]
        if len(balance_errors) > 10:
            notes.append(f"    ... and {len(balance_errors) - 10} more")
    else:
        results.append(("PASS", f"tag balance ({parser.opens} non-void tags, all matched)"))

    # -- 2. design version stamp -------------------------------------------
    stamp = STAMP_RE.search(source)
    if stamp:
        results.append(("PASS", f"design version stamp: v{stamp.group(1).lstrip('vV')}"))
    else:
        results.append(
            ("FAIL", "design version stamp: no <!-- design-system: vX.Y --> comment found")
        )

    # -- 3. required components --------------------------------------------
    toks = class_tokens(source)
    n_legend = sum(1 for t in toks if is_legend_container(t))
    n_fix = sum(1 for t in toks if is_fix_item(t))
    n_hero = sum(1 for t in toks if t == "band-hero")
    n_skill = sum(1 for t in toks if is_skill_card(t))
    n_closing = sum(1 for t in toks if is_closing(t)) + len(
        re.findall(r"<footer\b", source, re.I)
    )
    if n_legend >= 1 and n_fix >= 1:
        optional = f", closing: {n_closing} (optional since v1.1)" if n_closing else ""
        results.append(
            ("PASS", f"required components (legend: {n_legend}, fix items: {n_fix}{optional})")
        )
    elif n_hero >= 1 and n_skill >= 1:
        results.append(
            (
                "PASS",
                f"required components: band-card skeleton (hero: {n_hero}, skill cards: {n_skill})",
            )
        )
    else:
        results.append(
            (
                "FAIL",
                "required components: need legend + fix item (homework analysis) or "
                "band-hero + skill-card (band card, v1.3)",
            )
        )

    # -- 4. inline styles ---------------------------------------------------
    if inline_styles:
        results.append(("FAIL", f"no inline style= attributes ({len(inline_styles)} found)"))
        for ln, val in inline_styles[:10]:
            notes.append(f"    line {ln}: style=\"{val}\"")
        if len(inline_styles) > 10:
            notes.append(f"    ... and {len(inline_styles) - 10} more")
    else:
        results.append(("PASS", "no inline style= attributes"))

    # -- 5. @media print ----------------------------------------------------
    if re.search(r"@media[^{]*\bprint\b", css, re.I):
        results.append(("PASS", "@media print present"))
    else:
        results.append(("FAIL", "@media print missing"))

    # -- 6. focus styles ----------------------------------------------------
    if re.search(r":focus(?:-visible|-within)?\b", css, re.I):
        results.append(("PASS", ":focus / :focus-visible present"))
    else:
        results.append(("FAIL", ":focus / :focus-visible missing"))

    # -- 7. distinct font sizes <= 6 ---------------------------------------
    distinct = sorted({norm_size(v) for v, _ in sizes}) if sizes else []
    # clamp() values explode into several lengths; count plain declarations by
    # their leading value to stay honest about "design sizes".
    distinct_decl = sorted({norm_size(v) if "(" not in v else v.strip().lower() for v, _ in sizes})
    n = len(distinct_decl)
    if n <= MAX_DISTINCT_FONT_SIZES:
        results.append(("PASS", f"distinct font sizes: {n} (<= {MAX_DISTINCT_FONT_SIZES})"))
    else:
        results.append(
            ("FAIL", f"distinct font sizes: {n} (> {MAX_DISTINCT_FONT_SIZES}): {', '.join(distinct_decl)}")
        )

    # -- token checks -------------------------------------------------------
    font_tokens = color_tokens = None
    meta = {}
    spec_loaded = False
    tokens_path = args.tokens
    if not os.path.isfile(tokens_path):
        print(f"tokens: {tokens_path}")
        print("spec not found — token checks skipped")
    else:
        try:
            font_tokens, color_tokens, meta = load_token_sets(tokens_path)
            spec_loaded = True
            label = tokens_path
            if meta.get("version"):
                label += f" (v{str(meta['version']).lstrip('vV')})"
            print(f"tokens: {label}")
            if meta.get("version") and stamp:
                if str(meta["version"]).lstrip("vV") != stamp.group(1).lstrip("vV"):
                    notes.append(
                        f"    note: stamp v{stamp.group(1).lstrip('vV')} differs from tokens version {meta['version']}"
                    )
        except (OSError, json.JSONDecodeError) as exc:
            print(f"tokens: {tokens_path}")
            print(f"spec not found — token checks skipped (unreadable: {exc})")

    if font_tokens:
        # build violations: one example origin per off-scale value
        bad_map: dict[str, str] = {}
        for v, origin in sizes:
            for sv in size_tokens(v):
                if "var(" in sv:
                    bad_map.setdefault(sv, f"unresolved CSS variable ({origin})")
                elif sv not in font_tokens and sv not in bad_map:
                    bad_map[sv] = f"{v} ({origin})"
        if bad_map:
            results.append(
                ("FAIL", f"font sizes in tokens' scale ({len(bad_map)} off-scale value(s))")
            )
            for sv, example in sorted(bad_map.items())[:10]:
                notes.append(f"    {sv} <- {example}")
        else:
            results.append(
                ("PASS", f"all CSS font sizes in tokens' scale ({sorted(font_tokens)})")
            )
    else:
        reason = "spec not found" if not spec_loaded else "no font_sizes in spec"
        results.append(("SKIP", f"font sizes vs tokens.font_sizes ({reason})"))

    if color_tokens:
        bad_colors: dict[str, str] = {}
        hexes: dict[str, int] = {}
        for raw, origin in colors:
            nh = norm_hex(raw)
            hexes[nh] = hexes.get(nh, 0) + 1
            if nh not in color_tokens and nh not in bad_colors:
                bad_colors[nh] = origin
        if bad_colors:
            results.append(
                ("FAIL", f"hex colors in tokens' palette ({len(bad_colors)} off-palette value(s))")
            )
            for nh, origin in sorted(bad_colors.items())[:12]:
                notes.append(f"    {nh} ({origin})")
        else:
            results.append(
                ("PASS", f"all {len(hexes)} distinct hex colors in tokens' palette")
            )
    else:
        reason = "spec not found" if not spec_loaded else "no palette in spec"
        results.append(("SKIP", f"hex colors vs tokens.colors.allowed ({reason})"))

    # -- print --------------------------------------------------------------
    for status, label in results:
        print(f"[{status}] {label}")
    for note in notes:
        print(note)

    failures = sum(1 for s, _ in results if s == "FAIL")
    skipped = sum(1 for s, _ in results if s == "SKIP")
    passed = sum(1 for s, _ in results if s == "PASS")
    verdict = "exit 1" if failures else "exit 0"
    print(f"Result: {passed} passed, {failures} failed, {skipped} skipped → {verdict}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
