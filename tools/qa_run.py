#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_run.py — headless Playwright QA runner for single-file HTML artifacts.

Usage:
    python3 qa_run.py <file.html | directory> [--out DIR] [--prefix NAME]
                      [--allow-no-audio] [--timeout-ms MS]

Serves the file's directory over http://127.0.0.1:<free port> (file:// would
restrict web fonts), then for each HTML file checks, at desktop 1440x900 and
mobile 390x844 (DPR 2, is_mobile, has_touch):

  * console errors + page errors (listeners attached BEFORE goto)
  * horizontal overflow == documentElement.scrollWidth - clientWidth  (must be 0;
    when > 0 the culprit chain is located by display:none bisection)
  * document.fonts.status == 'loaded' + loaded/errored family list
  * at least one <audio> element carrying a <source> (--allow-no-audio to warn)
  * full-page + viewport screenshots -> {out}/{prefix}-{desktop|mobile}[-full].png

Full-page shots are taken in a separate device_scale_factor=1 context because
full-page captures at DPR>1 can crash the renderer on long pages.

Writes {out}/qa-report.json and prints a summary. Exit 0 if everything passed.
Requires: pip install playwright && python3 -m playwright install chromium --with-deps
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

VIEWPORTS = {
    "desktop": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1},
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
}

OVERFLOW_JS = (
    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
)

PROBE_JS = """() => {
  const de = document.documentElement;
  const faces = [...document.fonts].map(f => ({
    family: f.family, status: f.status, weight: f.weight, style: f.style
  }));
  const clean = s => s.replace(/["']/g, '').split(',')[0].trim();
  const loadedFams = [...new Set(faces.filter(f => f.status === 'loaded').map(f => clean(f.family)))];
  const errorFams = [...new Set(faces.filter(f => f.status === 'error').map(f => clean(f.family)))];
  const pendingFams = [...new Set(faces.filter(f => f.status === 'unloaded').map(f => clean(f.family)))];
  const audios = [...document.querySelectorAll('audio')].map(a => ({
    hasSource: !!a.querySelector('source'),
    sourceCount: a.querySelectorAll('source').length,
    sources: [...a.querySelectorAll('source')].map(s => s.getAttribute('src') || '(no src attr)'),
    readyState: a.readyState,
    src: a.getAttribute('src')
  }));
  return {
    title: document.title,
    clientWidth: de.clientWidth,
    scrollWidth: de.scrollWidth,
    innerWidth: window.innerWidth,
    overflowPx: de.scrollWidth - de.clientWidth,
    fontsStatus: document.fonts.status,
    fontFacesTotal: faces.length,
    fontFacesLoaded: faces.filter(f => f.status === 'loaded').length,
    fontFacesError: faces.filter(f => f.status === 'error').length,
    fontFamiliesLoaded: loadedFams,
    fontFamiliesError: errorFams,
    fontFamiliesPending: pendingFams,
    audios: audios,
    audioCount: audios.length,
    audioWithSource: audios.filter(a => a.hasSource).length
  };
}"""

# Overflow culprit bisection: hides top-level blocks (then descendants)
# with display:none and re-measures; the removal that brings overflow to 0
# names the culprit chain.
BISECT_JS = """(() => {
  const se = document.scrollingElement;
  const total = se.scrollWidth - document.documentElement.clientWidth;
  if (total <= 0) return {total: 0, culprit: null};
  const desc = el => el.tagName + (el.id ? '#' + el.id : '') +
    (typeof el.className === 'string' && el.className ? '.' + el.className.split(' ')[0] : '');
  const tops = [...document.querySelectorAll('body > section, body > div, body > footer, body > table')];
  for (const el of tops) {
    const prev = el.style.display;
    el.style.display = 'none';
    const now = se.scrollWidth - document.documentElement.clientWidth;
    el.style.display = prev;
    if (now <= 0) {
      let node = el;
      const chain = [desc(el)];
      for (let depth = 0; depth < 6; depth++) {
        let best = null;
        for (const child of node.querySelectorAll('*')) {
          const p2 = child.style.display;
          child.style.display = 'none';
          const n2 = se.scrollWidth - document.documentElement.clientWidth;
          child.style.display = p2;
          if (n2 <= 0) { best = child; break; }
        }
        if (!best) break;
        node = best;
        chain.push(desc(node));
      }
      return {total, culprit: chain.join(' < ')};
    }
  }
  return {total, culprit: 'not inside a top-level block (check fixed/absolute decor)'};
})()"""


# --------------------------------------------------------------------------
# tiny static server (stdlib)
# --------------------------------------------------------------------------
class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request logging
        pass


def start_server(root: Path):
    handler = functools.partial(_QuietHandler, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# --------------------------------------------------------------------------
# browser lifecycle (relaunch after a crash so one blow-up doesn't kill the run)
# --------------------------------------------------------------------------
class BrowserHolder:
    def __init__(self, pw):
        self.pw = pw
        self.browser = None

    async def get(self, force=False):
        if force or self.browser is None or not self.browser.is_connected():
            if self.browser is not None:
                try:
                    if self.browser.is_connected():
                        await self.browser.close()
                except Exception:
                    pass
            self.browser = await self.pw.chromium.launch()
        return self.browser

    async def close(self):
        if self.browser is not None and self.browser.is_connected():
            await self.browser.close()


# --------------------------------------------------------------------------
# core checks
# --------------------------------------------------------------------------
async def qa_page(holder: BrowserHolder, url: str, out_dir: Path, prefix: str,
                  allow_no_audio: bool, timeout_ms: int):
    report = {"url": url, "viewports": {}, "screenshots": [], "runner_errors": []}

    for vp_name, vp_opts in VIEWPORTS.items():
        vp_report = {
            "viewport": f"{vp_opts['viewport']['width']}x{vp_opts['viewport']['height']}"
            f" dpr{vp_opts['device_scale_factor']}{' mobile-emulation' if vp_opts.get('is_mobile') else ''}",
            "console_errors": [],
            "console_warnings": [],
            "page_errors": [],
            "failed_requests": [],
            "screenshots": [],
        }
        try:
            browser = await holder.get()
            ctx = await browser.new_context(**vp_opts)
            page = await ctx.new_page()

            # listeners BEFORE goto
            page.on("console", lambda m, r=vp_report: (
                r["console_errors"].append(f"[console.{m.type}] {m.text}")
                if m.type == "error" else
                r["console_warnings"].append(f"[console.{m.type}] {m.text}")
                if m.type == "warning" else None))
            page.on("pageerror", lambda e, r=vp_report: r["page_errors"].append(str(e)))
            page.on("requestfailed", lambda req, r=vp_report: r["failed_requests"].append(
                f"{req.url} — {req.failure or 'failed'}"))

            await page.goto(url, wait_until="load", timeout=timeout_ms)
            try:
                await page.wait_for_function(
                    "document.fonts.status === 'loaded'", timeout=15000)
            except Exception:
                pass  # probe reports the real status below
            await page.wait_for_timeout(700)  # reveal/entry animations

            probe = await page.evaluate(PROBE_JS)
            vp_report.update(
                title=probe["title"],
                client_width=probe["clientWidth"],
                scroll_width=probe["scrollWidth"],
                inner_width=probe["innerWidth"],
                overflow_px=probe["overflowPx"],
                fonts={
                    "status": probe["fontsStatus"],
                    "faces_total": probe["fontFacesTotal"],
                    "faces_loaded": probe["fontFacesLoaded"],
                    "faces_error": probe["fontFacesError"],
                    "families_loaded": probe["fontFamiliesLoaded"],
                    "families_error": probe["fontFamiliesError"],
                    "families_pending": probe["fontFamiliesPending"],
                },
                audio={
                    "count": probe["audioCount"],
                    "with_source": probe["audioWithSource"],
                    "detail": probe["audios"],
                },
            )

            if probe["overflowPx"] > 0:
                try:
                    vp_report["overflow_culprit"] = await page.evaluate(BISECT_JS)
                except Exception as exc:
                    vp_report["overflow_culprit"] = {"error": str(exc)}

            # viewport screenshot in the emulated context
            shot = out_dir / f"{prefix}-{vp_name}.png"
            await page.screenshot(path=str(shot), timeout=timeout_ms)
            vp_report["screenshots"].append(shot.name)
            report["screenshots"].append(str(shot))

            await ctx.close()

            # full-page screenshot in a SEPARATE DPR=1 context (renderer-crash guard)
            fctx_opts = dict(vp_opts)
            fctx_opts["device_scale_factor"] = 1
            fctx = await browser.new_context(**fctx_opts)
            fpage = await fctx.new_page()
            await fpage.goto(url, wait_until="load", timeout=timeout_ms)
            await fpage.wait_for_timeout(700)
            fshot = out_dir / f"{prefix}-{vp_name}-full.png"
            await fpage.screenshot(path=str(fshot), full_page=True, timeout=timeout_ms)
            vp_report["screenshots"].append(fshot.name)
            report["screenshots"].append(str(fshot))
            await fctx.close()

        except Exception as exc:  # crash / timeout on this viewport only
            vp_report["runner_error"] = f"{type(exc).__name__}: {exc}"
            report["runner_errors"].append(f"{vp_name}: {vp_report['runner_error']}")
            try:
                await holder.get(force=True)  # fresh browser for the next pass
            except Exception:
                pass

        report["viewports"][vp_name] = vp_report

    # -- pass/fail verdict --------------------------------------------------
    checks = {}
    for vp_name, r in report["viewports"].items():
        if "runner_error" in r:
            checks[f"{vp_name}.runner"] = False
            continue
        checks[f"{vp_name}.console_errors"] = len(r["console_errors"]) == 0
        checks[f"{vp_name}.page_errors"] = len(r["page_errors"]) == 0
        checks[f"{vp_name}.overflow"] = r.get("overflow_px", 1) == 0
        checks[f"{vp_name}.fonts_loaded"] = (
            r["fonts"]["status"] == "loaded"
            and r["fonts"]["faces_error"] == 0
            and len(r["fonts"]["families_loaded"]) > 0
        )
        audio_ok = r["audio"]["count"] >= 1 and r["audio"]["with_source"] >= 1 and \
            r["audio"]["with_source"] == r["audio"]["count"]
        if allow_no_audio and r["audio"]["count"] == 0:
            checks[f"{vp_name}.audio_with_source"] = True  # downgraded by flag
            r["audio"]["downgraded"] = "no audio elements; allowed by --allow-no-audio"
        else:
            checks[f"{vp_name}.audio_with_source"] = audio_ok

    report["checks"] = checks
    report["pass"] = all(checks.values()) and not report["runner_errors"]
    return report


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def collect_targets(path: Path):
    """-> (serve_root, [relative html paths])"""
    if path.is_file():
        return path.parent, [path.name]
    if path.is_dir():
        files = sorted(p.name for p in path.iterdir() if p.suffix.lower() == ".html")
        return path, files
    raise SystemExit(f"error: no such file or directory: {path}")


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "artifact"


async def async_main(args):
    root, files = collect_targets(Path(args.target).resolve())
    if not files:
        raise SystemExit(f"error: no .html files found in {root}")

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    srv, port = start_server(root)
    print(f"== qa_run == serving {root} at http://127.0.0.1:{port}/")

    results = []
    async with async_playwright() as p:
        holder = BrowserHolder(p)
        browser = await holder.get()
        print(f"chromium {browser.version}")
        try:
            for rel in files:
                url = f"http://127.0.0.1:{port}/" + quote(rel)
                prefix = args.prefix or sanitize(Path(rel).stem)
                print(f"\n--- {rel}  (prefix: {prefix}) ---")
                report = await qa_page(
                    holder, url, out_dir, prefix, args.allow_no_audio,
                    args.timeout_ms)
                report["file"] = str(root / rel)
                report["prefix"] = prefix
                results.append(report)

                for vp_name, r in report["viewports"].items():
                    if "runner_error" in r:
                        print(f"[{vp_name:>7}] RUNNER ERROR: {r['runner_error']}")
                        continue
                    ov = r.get("overflow_px", "?")
                    culprit = ""
                    if ov and ov > 0:
                        c = r.get("overflow_culprit") or {}
                        culprit = f"  culprit: {c.get('culprit')}"
                    print(
                        f"[{vp_name:>7}] errors: {len(r['console_errors'])} console / "
                        f"{len(r['page_errors'])} page · overflow: {ov}px{culprit} · "
                        f"fonts: {r['fonts']['status']} "
                        f"({', '.join(r['fonts']['families_loaded']) or 'none'}"
                        + (f", ERRORS: {', '.join(r['fonts']['families_error'])}"
                           if r["fonts"]["families_error"] else "") + ") · "
                        f"audio: {r['audio']['with_source']}/{r['audio']['count']} with source · "
                        f"shots: {', '.join(r['screenshots'])}"
                    )
                    for e in r["console_errors"][:5]:
                        print(f"            {e}")
                    for e in r["page_errors"][:5]:
                        print(f"            [pageerror] {e}")
                verdict = "PASS" if report["pass"] else "FAIL"
                failed = [k for k, v in report["checks"].items() if not v]
                print(f"RESULT: {verdict}" + (f"  (failed: {', '.join(failed)})" if failed else ""))
        finally:
            await holder.close()
    srv.shutdown()

    report_path = out_dir / "qa-report.json"
    payload = {
        "tool": "qa_run.py",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "viewports": {k: v["viewport"] for k, v in VIEWPORTS.items()},
        "results": results,
        "pass": all(r["pass"] for r in results),
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nreport: {report_path}")
    overall = "PASS" if payload["pass"] else "FAIL"
    print(f"OVERALL: {overall} ({sum(1 for r in results if r['pass'])}/{len(results)} files passed)")
    return 0 if payload["pass"] else 1


def main():
    ap = argparse.ArgumentParser(description="Headless Playwright QA for HTML artifacts.")
    ap.add_argument("target", help="path to a .html file or a directory of .html files")
    ap.add_argument("--out", default="./qa-out",
                    help="output dir for screenshots + qa-report.json")
    ap.add_argument("--prefix", default=None,
                    help="screenshot filename prefix (default: per-file stem)")
    ap.add_argument("--allow-no-audio", action="store_true",
                    help="treat a page without <audio> as a warning, not a failure")
    ap.add_argument("--timeout-ms", type=int, default=45000,
                    help="navigation/screenshot timeout in ms (default 45000)")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
