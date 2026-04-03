#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web interface for YOURLS-diff.
"""

from __future__ import annotations

import argparse
import html
import mimetypes
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

from socketserver import ThreadingMixIn

from web.yourls_diff_web_backend import fetch_releases, run_diff, safe_name

DATA_DIR = os.environ.get("YOURLS_DIFF_DATA_DIR", os.path.join(os.getcwd(), "data"))
CACHE_DIR = os.environ.get("YOURLS_DIFF_CACHE_DIR", os.path.join(DATA_DIR, "cache"))
OUTPUT_DIR = os.environ.get("YOURLS_DIFF_OUTPUT_DIR", os.path.join(DATA_DIR, "outputs"))
DEFAULT_VERIFY_SSL = os.environ.get("YOURLS_DIFF_VERIFY_SSL", "1") not in {"0", "false", "False"}
GENERIC_ERROR_MESSAGE = "An internal error occurred while processing the request."


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _read_form(environ):
    length = int(environ.get("CONTENT_LENGTH") or 0)
    raw = environ["wsgi.input"].read(length).decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}


def _escape(value):
    return html.escape("" if value is None else str(value), quote=True)


def _safe_header_filename(value):
    name = os.path.basename("" if value is None else str(value))
    name = name.replace("\r", "").replace("\n", "").replace('"', "")
    return name or "download"


def _safe_served_path(base_dir, rel_dir, rel_name):
    safe_base = os.path.realpath(os.path.expanduser(base_dir))
    safe_target = os.path.realpath(os.path.join(safe_base, rel_dir, rel_name))
    if safe_target != safe_base and not safe_target.startswith(safe_base + os.sep):
        raise ValueError("Forbidden")
    return safe_target


def _open_served_file(base_dir, rel_dir, rel_name, mode, **kwargs):
    return open(_safe_served_path(base_dir, rel_dir, rel_name), mode, **kwargs)


def _open_text_target(path, base_dir):
    return open(_safe_served_path(base_dir, "", os.path.relpath(path, base_dir)), "r", encoding="utf-8", errors="replace")


def _download_link(path):
    if not path:
        return None
    rel_dir = os.path.relpath(os.path.dirname(path), OUTPUT_DIR)
    rel_name = os.path.basename(path)
    return f"/download/{quote(rel_dir, safe='')}/{quote(rel_name, safe='')}"


def _view_link(path, return_to=None):
    if not path:
        return None
    rel_dir = os.path.relpath(os.path.dirname(path), OUTPUT_DIR)
    rel_name = os.path.basename(path)
    url = f"/view/{quote(rel_dir, safe='')}/{quote(rel_name, safe='')}"
    if return_to:
        url += f"?return_to={quote(return_to, safe='')}"
    return url


def _is_viewable_text(path):
    name = os.path.basename(path or "").lower()
    return name.endswith((".txt", ".sh", ".winscp.txt"))


def _is_persistent_path(path):
    expanded = os.path.realpath(os.path.expanduser(path))
    roots = {os.path.realpath(DATA_DIR), os.path.realpath(CACHE_DIR), os.path.realpath(OUTPUT_DIR)}
    return any(expanded == root or expanded.startswith(root + os.sep) for root in roots)


def _pair_output_dir(old_tag, new_tag):
    return os.path.join(OUTPUT_DIR, f"{safe_name(old_tag)}-to-{safe_name(new_tag)}")


def _output_stats():
    if not os.path.isdir(OUTPUT_DIR):
        return {"patch_sets": 0, "files": 0, "viewable": 0, "downloadable": 0, "persisted": False}

    patch_sets = 0
    files = 0
    viewable = 0
    downloadable = 0

    for entry in os.scandir(OUTPUT_DIR):
        if not entry.is_dir():
            continue
        pair_files = []
        for root, _, names in os.walk(entry.path):
            for name in names:
                path = os.path.join(root, name)
                pair_files.append(path)
        if pair_files:
            patch_sets += 1
        for path in pair_files:
            files += 1
            if _is_viewable_text(path):
                viewable += 1
            if os.path.basename(path).lower().endswith(".zip"):
                downloadable += 1

    return {
        "patch_sets": patch_sets,
        "files": files,
        "viewable": viewable,
        "downloadable": downloadable,
        "persisted": True,
    }


def _render_layout(content="", title="YOURLS-diff web", releases=None, message=None):
    releases = releases or []
    old_releases = releases[1:] if len(releases) > 1 else []
    new_releases = releases

    def _release_options(items, selected_tag=None, start_index=0):
        options = []
        for idx, release in enumerate(items, start=start_index):
            tag = release["tag_name"]
            published = release.get("published_at")
            if published:
                label = f"{tag} ({published[:10]})"
            else:
                label = tag
            selected = ' selected' if selected_tag == tag else ''
            options.append(
                f'<option value="{_escape(tag)}" data-release-index="{idx}"{selected}>{_escape(label)}</option>'
            )
        return "\n".join(options)

    old_default = old_releases[0]["tag_name"] if old_releases else (releases[0]["tag_name"] if releases else "")
    new_default = releases[0]["tag_name"] if releases else ""
    old_options = _release_options(old_releases, selected_tag=old_default, start_index=1)
    new_options = _release_options(new_releases, selected_tag=new_default, start_index=0)
    output_stats = _output_stats()
    persistent_cache = _is_persistent_path(CACHE_DIR)
    persistent_outputs = _is_persistent_path(OUTPUT_DIR)
    persist_hint = ""
    if not (persistent_cache and persistent_outputs):
        persist_hint = """
    <div class="footer-note">
      Tip: if you run this in Docker, mount the cache and output directories as volumes so the archive history survives container restarts.
    </div>
    """

    nav = f"""
    <div class="topbar">
      <div>
        <div class="eyebrow">YOURLS-diff</div>
        <h1>{_escape(title)}</h1>
      </div>
    </div>
    """
    notice = f'<div class="notice">{_escape(message)}</div>' if message else ""
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1220;
      --panel: #11192c;
      --panel-2: #15213a;
      --text: #e9eefb;
      --muted: #9fb1d1;
      --accent: #6ee7ff;
      --accent-2: #8b5cf6;
      --border: rgba(255,255,255,.12);
      --ok: #16a34a;
      --warn: #d97706;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(139,92,246,.30), transparent 35%),
        radial-gradient(circle at top right, rgba(110,231,255,.16), transparent 30%),
        linear-gradient(180deg, #08101d, #0b1220 60%, #070d16);
      min-height: 100vh;
    }}
    .shell {{
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 36px 0 48px;
    }}
    .topbar {{
      display: flex;
      gap: 20px;
      justify-content: space-between;
      align-items: flex-end;
      margin-bottom: 28px;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: .14em;
      color: var(--accent);
      font-size: 12px;
      margin-bottom: 8px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(34px, 4.2vw, 60px);
      line-height: .95;
      letter-spacing: -0.03em;
    }}
    .meta {{
      color: var(--muted);
      text-align: right;
      font-size: 14px;
      line-height: 1.6;
      padding-top: 8px;
    }}
    .notice {{
      margin: 0 0 20px;
      padding: 14px 16px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.04);
      border-radius: 14px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.1fr .9fr;
      gap: 24px;
    }}
    .card {{
      background: rgba(17,25,44,.86);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 26px;
      box-shadow: 0 24px 80px rgba(0,0,0,.28);
      backdrop-filter: blur(14px);
    }}
    .card h2 {{
      margin: 0 0 16px;
      font-size: 22px;
    }}
    .lead {{
      margin: 0 0 18px;
      color: var(--muted);
      line-height: 1.55;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    label {{
      display: block;
      font-size: 14px;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    input[type=text], select {{
      width: 100%;
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      padding: 12px 14px;
      border-radius: 12px;
      font-size: 15px;
    }}
    select {{
      appearance: none;
      -webkit-appearance: none;
      -moz-appearance: none;
    }}
    .row-full {{
      grid-column: 1 / -1;
    }}
    select option:disabled {{
      color: rgba(233, 238, 251, .32);
    }}
    .actions {{
      display: flex;
      gap: 12px;
      align-items: center;
      margin-top: 22px;
      flex-wrap: wrap;
    }}
    button {{
      appearance: none;
      -webkit-appearance: none;
      border: 0;
      background: linear-gradient(135deg, var(--accent), #7cdbff);
      color: #07111f;
      font: inherit;
      font-weight: 700;
      padding: 12px 18px;
      border-radius: 999px;
      font-size: 15px;
      cursor: pointer;
      line-height: 1;
      box-shadow: 0 12px 26px rgba(110,231,255,.14);
    }}
    .secondary {{
      color: var(--muted);
      font-size: 14px;
    }}
    .field-hint {{
      margin-top: 6px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.4;
    }}
    .full-width {{
      grid-column: 1 / -1;
    }}
    .result-list {{
      display: grid;
      gap: 12px;
    }}
    .result-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 12px;
    }}
    .result-head h2 {{
      margin-bottom: 8px;
    }}
    .result-item {{
      padding: 16px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.04);
    }}
    .result-item strong {{
      display: block;
      margin-bottom: 4px;
    }}
    .result-item code, .mono {{
      color: var(--accent);
      word-break: break-word;
    }}
    a.button {{
      display: inline-block;
      margin-top: 10px;
      text-decoration: none;
      background: rgba(255,255,255,.08);
      color: var(--text);
      padding: 9px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
    }}
    .button-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}
    a.button.secondary {{
      background: rgba(110, 231, 255, .08);
    }}
    a.button.secondary.copied {{
      background: rgba(110,231,255,.16);
      border-color: rgba(110,231,255,.35);
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .result-summary {{
      display: grid;
      grid-template-columns: 1.2fr .8fr .8fr;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .mini-stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 8px;
    }}
    .mini-stats.overview {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .mini-stat {{
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.03);
    }}
    .mini-stat .label {{
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    .mini-stat .value {{
      font-size: 16px;
      font-weight: 800;
      color: var(--text);
    }}
    .how-list {{
      margin: 14px 0 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.55;
    }}
    .how-list li + li {{
      margin-top: 8px;
    }}
    .summary-card {{
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.03);
    }}
    .summary-head {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 6px;
    }}
    .summary-icon {{
      width: 28px;
      height: 28px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      background: rgba(255,255,255,.06);
      color: var(--accent);
      flex: 0 0 auto;
    }}
    .summary-icon svg {{
      width: 15px;
      height: 15px;
      stroke: currentColor;
      fill: none;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .summary-label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }}
    .summary-value {{
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
    }}
    .artifact-list {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .artifact-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.03);
      min-width: 0;
    }}
    .artifact-left {{
      min-width: 0;
      display: grid;
      gap: 4px;
    }}
    .artifact-head {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 46px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .08em;
      color: #07111f;
      background: var(--accent);
      flex: 0 0 auto;
    }}
    .badge.zip {{ background: #7cdbff; }}
    .badge.txt {{ background: #a78bfa; }}
    .badge.sh {{ background: #86efac; }}
    .artifact-title {{
      font-weight: 700;
      min-width: 0;
    }}
    .artifact-meta {{
      color: var(--muted);
      font-size: 13px;
      word-break: break-word;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .footer-note {{
      margin-top: 20px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .summary-preview {{
      margin: 0 0 14px;
      padding: 16px 16px 14px;
      border-radius: 16px;
      border: 1px solid rgba(110,231,255,.16);
      background: rgba(255,255,255,.03);
    }}
    .summary-preview-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }}
    .summary-preview-label {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .1em;
      color: var(--accent);
      font-weight: 800;
    }}
    .summary-preview-path {{
      font-size: 12px;
      color: var(--muted);
      word-break: break-word;
      text-align: right;
    }}
    .summary-preview pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.6;
      font-size: 14px;
    }}
    .available-files-title {{
      margin: 28px 0 12px;
      font-size: 22px;
      line-height: 1.1;
      letter-spacing: -0.02em;
    }}
    .how-points {{
      margin: 16px 0 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 10px;
    }}
    .how-point {{
      display: flex;
      gap: 12px;
      align-items: flex-start;
      color: var(--muted);
      line-height: 1.5;
      font-size: 14px;
      padding: 2px 0;
    }}
    .how-marker {{
      width: 8px;
      height: 8px;
      margin-top: 7px;
      border-radius: 999px;
      background: var(--accent);
      flex: 0 0 auto;
      box-shadow: 0 0 0 4px rgba(110,231,255,.12);
    }}
    .how-copy {{
      min-width: 0;
      flex: 1 1 auto;
    }}
    .how-point strong {{
      display: block;
      color: var(--text);
      margin-bottom: 2px;
      font-size: 14px;
    }}
    .how-point span {{
      display: block;
      color: var(--muted);
    }}
    .inline-note {{
      display: inline-block;
      color: var(--accent);
    }}
    .scroll-top {{
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 20;
      opacity: 0;
      pointer-events: none;
      transform: translateY(14px);
      transition: opacity .18s ease, transform .18s ease;
    }}
    .scroll-top.visible {{
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }}
    @media (max-width: 860px) {{
      .grid, .form-grid {{ grid-template-columns: 1fr; }}
      .meta {{ text-align: left; }}
      .topbar {{ flex-direction: column; }}
      .mini-stats.overview {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .summary-grid {{ grid-template-columns: 1fr; }}
      .result-summary {{ grid-template-columns: 1fr; }}
      .artifact-list {{ grid-template-columns: 1fr; }}
      .artifact-row {{ align-items: flex-start; flex-direction: column; }}
      .result-head {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    {nav}
    {notice}
    <div class="grid">
      <div class="card">
        <h2>Generate a patch</h2>
        <p class="lead">Choose two official YOURLS releases. The app caches archives on disk, so repeated comparisons do not redownload the same ZIP files.</p>
        <form method="post" action="/generate">
          <div class="form-grid">
            <div>
              <label for="old_tag">Old release</label>
              <select id="old_tag" name="old_tag" data-old-select>
                {old_options}
              </select>
              <div class="field-hint">The newest release is excluded here by design.</div>
            </div>
            <div>
              <label for="new_tag">New release</label>
              <select id="new_tag" name="new_tag" data-new-select>
                {new_options}
              </select>
              <div class="field-hint">This list includes the latest official release.</div>
            </div>
          </div>
          <div class="actions">
            <button type="submit">Generate</button>
            <div class="secondary">Summary, removed-file list, and WinSCP script are generated automatically.</div>
          </div>
          <div class="mini-stats overview">
            <div class="mini-stat">
              <span class="label">Patch sets</span>
              <div class="value">{output_stats["patch_sets"]}</div>
            </div>
            <div class="mini-stat">
              <span class="label">Stored files</span>
              <div class="value">{output_stats["files"]}</div>
            </div>
            <div class="mini-stat">
              <span class="label">Viewable</span>
              <div class="value">{output_stats["viewable"]}</div>
            </div>
            <div class="mini-stat">
              <span class="label">ZIP downloads</span>
              <div class="value">{output_stats["downloadable"]}</div>
            </div>
            <div class="mini-stat">
              <span class="label">Persisted</span>
              <div class="value">{'yes' if (persistent_cache and persistent_outputs) else 'no'}</div>
            </div>
          </div>
        </form>
      </div>
      <div class="card">
        <h2>How it works</h2>
        <ul class="how-points">
          <li class="how-point"><span class="how-marker" aria-hidden="true"></span><div class="how-copy"><strong>Output model</strong><span>Each release pair maps to one output folder, so repeated requests reuse the same generated artifacts instead of creating duplicates.</span></div></li>
          <li class="how-point"><span class="how-marker" aria-hidden="true"></span><div class="how-copy"><strong>Cache layer</strong><span>Release ZIPs are stored under <span class="mono">{_escape(CACHE_DIR)}</span> and reused across runs.</span></div></li>
          <li class="how-point"><span class="how-marker" aria-hidden="true"></span><div class="how-copy"><strong>File access</strong><span>Text outputs can be opened in-browser, while ZIP files stay available for download.</span></div></li>
          <li class="how-point"><span class="how-marker" aria-hidden="true"></span><div class="how-copy"><strong>Project origin</strong><span>This interface is the web edition of the YOURLS-diff project and depends on the underlying repository and its patch-generation logic.</span></div></li>
        </ul>
      </div>
    </div>
    {content}
    {persist_hint}
  </div>
  <button type="button" class="button scroll-top" data-scroll-top>Go to top</button>
  <script>
    (() => {{
      const oldSelect = document.querySelector("[data-old-select]");
      const newSelect = document.querySelector("[data-new-select]");
      const topButton = document.querySelector("[data-scroll-top]");
      const refreshNewOptions = () => {{
        if (!oldSelect || !newSelect) return;
        const oldIndex = Number(oldSelect.selectedOptions[0]?.dataset.releaseIndex ?? "0");
        Array.from(newSelect.options).forEach((option) => {{
          const index = Number(option.dataset.releaseIndex ?? "0");
          const enabled = index < oldIndex;
          option.disabled = !enabled;
          option.hidden = !enabled;
        }});

        if (newSelect.selectedOptions[0]?.disabled) {{
          const nextEnabled = Array.from(newSelect.options).find((option) => !option.disabled);
          if (nextEnabled) {{
            newSelect.value = nextEnabled.value;
          }}
        }}
      }};

      if (oldSelect && newSelect) {{
        oldSelect.addEventListener("change", () => {{
          refreshNewOptions();
        }});
        refreshNewOptions();
      }}
      const syncTopButton = () => {{
        if (!topButton) return;
        topButton.classList.toggle("visible", window.scrollY > 280);
      }};
      if (topButton) {{
        topButton.addEventListener("click", () => {{
          window.scrollTo({{ top: 0, behavior: "smooth" }});
        }});
        window.addEventListener("scroll", syncTopButton, {{ passive: true }});
        syncTopButton();
      }}
    }})();
  </script>
</body>
</html>"""


def _render_result(result, releases=None, auto_scroll=False):
    def summary_icon(kind):
        icons = {
            "compared": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 5h5M9 11h5M9 5l2-2 2 2M7 11l-2 2-2-2"/></svg>',
            "changed": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10"/></svg>',
            "removed": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg>',
        }
        return icons[kind]

    def badge_for(title):
        if title == "Patch ZIP":
            return "ZIP", "zip"
        if title in {"Deploy script", "WinSCP script"}:
            return "SH", "sh"
        return "TXT", "txt"

    artifacts = []
    def add_item(title, value, file_path=None):
        if value:
            links = []
            if file_path:
                if _is_viewable_text(file_path):
                    links.append(f'<a class="button secondary" href="{_escape(_view_link(file_path, return_to=result_url + "#files-section"))}">View</a>')
                links.append(f'<a class="button" href="{_escape(_download_link(file_path))}">Download</a>')
            link = f'<div class="button-row">{"".join(links)}</div>' if links else ""
            badge_label, badge_class = badge_for(title)
            artifacts.append(
                f'''
                <div class="artifact-row">
                  <div class="artifact-left">
                    <div class="artifact-head"><span class="badge {badge_class}">{_escape(badge_label)}</span><div class="artifact-title">{_escape(title)}</div></div>
                    <div class="artifact-meta mono">{_escape(os.path.basename(value))}</div>
                  </div>
                  {link}
                </div>
                '''
            )

    result_url = f"/result?old={quote(result.old_tag, safe='')}&new={quote(result.new_tag or '', safe='')}"

    add_item("Patch ZIP", result.zip_path, file_path=result.zip_path)
    add_item("Manifest", result.manifest_path, file_path=result.manifest_path)
    add_item("Removed manifest", result.removed_manifest_path, file_path=result.removed_manifest_path)
    add_item("Deploy script", result.deploy_script_path, file_path=result.deploy_script_path)
    add_item("WinSCP script", result.winscp_script_path, file_path=result.winscp_script_path)

    summary_body = ""
    summary_download = ""
    if result.summary_path and os.path.isfile(result.summary_path):
        with open(result.summary_path, "r", encoding="utf-8", errors="replace") as f:
            summary_text = f.read().strip()
        summary_body = f"""
        <div class="summary-preview">
          <div class="summary-preview-head">
            <div class="summary-preview-label">Summary</div>
            <div class="summary-preview-path">{_escape(os.path.basename(result.summary_path))}</div>
          </div>
          <pre>{_escape(summary_text)}</pre>
        </div>
        """
        summary_download = f'<a class="button secondary" href="{_escape(_download_link(result.summary_path))}">Download summary</a>'

    body = f"""
    <div class="card" id="result-box" style="margin-top: 18px;">
      <div class="result-head">
        <div>
          <h2>Result</h2>
          <p class="lead">{_escape(result.message or "Patch generated.")}</p>
        </div>
        <div class="button-row">
          <a class="button secondary" href="/">New patch</a>
          <a class="button secondary" href="{_escape(result_url)}">Refresh</a>
          <a class="button secondary" href="{_escape(result_url)}" data-copy-link data-copy-url="{_escape(result_url)}">Copy link</a>
          <a class="button secondary" href="#files-section">Files</a>
        </div>
      </div>
      <div class="result-summary">
        <div class="summary-card">
          <div class="summary-head"><span class="summary-icon">{summary_icon("compared")}</span><div class="summary-label">Compared</div></div>
          <div class="summary-value">{_escape(result.old_tag)} → {_escape(result.new_tag)}</div>
        </div>
        <div class="summary-card">
          <div class="summary-head"><span class="summary-icon">{summary_icon("changed")}</span><div class="summary-label">Added / Modified</div></div>
          <div class="summary-value">{len(result.changed_files)}</div>
        </div>
        <div class="summary-card">
          <div class="summary-head"><span class="summary-icon">{summary_icon("removed")}</span><div class="summary-label">Removed</div></div>
          <div class="summary-value">{len(result.removed_files)}</div>
        </div>
      </div>
      {summary_body}
      <div class="button-row" style="margin: 12px 0 14px;">
        {summary_download}
      </div>
      <h3 class="available-files-title" id="files-section">Available files</h3>
      <div class="artifact-list">
        {''.join(artifacts)}
      </div>
    </div>
    <script>
      (() => {{
        const box = document.getElementById("result-box");
        if (box && {str(bool(auto_scroll)).lower()}) {{
          requestAnimationFrame(() => {{
            box.scrollIntoView({{ behavior: "smooth", block: "start" }});
          }});
          try {{
            const url = new URL(window.location.href);
            url.searchParams.delete("generated");
            window.history.replaceState(null, "", url.pathname + url.search + url.hash);
          }} catch (error) {{}}
        }}
        const copyButton = document.querySelector("[data-copy-link]");
        if (copyButton) {{
          const originalLabel = copyButton.textContent;
          copyButton.addEventListener("click", async (event) => {{
            event.preventDefault();
            const value = copyButton.getAttribute("data-copy-url") || window.location.href;
            try {{
              await navigator.clipboard.writeText(new URL(value, window.location.origin).href);
              copyButton.classList.add("copied");
              copyButton.textContent = "Copied";
              window.setTimeout(() => {{
                copyButton.classList.remove("copied");
                copyButton.textContent = originalLabel;
              }}, 1400);
            }} catch (error) {{
              window.prompt("Copy this link", new URL(value, window.location.origin).href);
            }}
          }});
        }}
      }})();
    </script>
    """
    return _render_layout(content=body, title=f"YOURLS-diff {result.old_tag} → {result.new_tag}", releases=releases, message=None)


def _serve_file(environ, start_response, base_dir, rel_dir, rel_name, attachment=True):
    try:
        target = _safe_served_path(base_dir, rel_dir, rel_name)
    except ValueError:
        start_response("403 Forbidden", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Forbidden"]
    if not os.path.isfile(target):
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not found"]

    ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
    headers = [
        ("Content-Type", ctype),
        ("Content-Length", str(os.path.getsize(target))),
    ]
    disposition = "attachment" if attachment else "inline"
    headers.append(("Content-Disposition", f'{disposition}; filename="{_safe_header_filename(target)}"'))
    start_response("200 OK", headers)
    rel_target = os.path.relpath(target, base_dir)
    with _open_served_file(base_dir, "", rel_target, "rb") as f:
        return [f.read()]


def _render_text_view(target_path, title, back_url=None):
    with _open_text_target(target_path, OUTPUT_DIR) as f:
        content = f.read()
    safe_back_url = back_url if back_url and back_url.startswith("/") else "/"
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} - YOURLS-diff</title>
  <style>
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0b1220;
      color: #e9eefb;
      padding: 28px;
    }}
    html {{ scroll-behavior: smooth; }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    .card {{
      border: 1px solid rgba(255,255,255,.12);
      border-radius: 16px;
      background: rgba(17,25,44,.92);
      padding: 20px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    .meta {{
      color: #9fb1d1;
      margin-bottom: 16px;
      word-break: break-word;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      line-height: 1.5;
      color: #dbeafe;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }}
    .actions .home {{
      background: rgba(255,255,255,.08);
      color: #e9eefb;
      border: 1px solid rgba(255,255,255,.12);
    }}
    a {{
      color: #07111f;
      background: #6ee7ff;
      text-decoration: none;
      padding: 8px 12px;
      border-radius: 999px;
      font-weight: 700;
    }}
    a.secondary {{
      background: rgba(255,255,255,.08);
      color: #e9eefb;
      border: 1px solid rgba(255,255,255,.12);
    }}
    button.secondary {{
      appearance: none;
      -webkit-appearance: none;
      background: rgba(255,255,255,.08);
      color: #e9eefb;
      border: 1px solid rgba(255,255,255,.12);
      text-decoration: none;
      padding: 8px 12px;
      border-radius: 999px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>{_escape(title)}</h1>
      <div class="actions">
        <button type="button" class="secondary" onclick="history.back()">Back</button>
        <a href="{_escape(safe_back_url)}" class="secondary">Return to result</a>
        <a href="/" class="secondary">Home</a>
        <a href="{_escape(_download_link(target_path))}">Download</a>
      </div>
      <pre>{_escape(content)}</pre>
    </div>
  </div>
</body>
</html>"""


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    releases = []
    error = None
    try:
        releases = fetch_releases(DEFAULT_VERIFY_SSL, cache_dir=CACHE_DIR)
    except Exception as exc:
        _log_exception("Failed to load release list", exc)
        error = "Unable to load release list right now."

    if path == "/" and method == "GET":
        body = _render_layout(releases=releases, message=error)
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [body.encode("utf-8")]

    if path == "/generate" and method == "POST":
        form = _read_form(environ)
        old_tag = form.get("old_tag", "").strip()
        new_tag = form.get("new_tag", "").strip() or None
        if not old_tag:
            body = _render_layout(content=_render_error("Old release is required."), releases=releases, message=error)
            start_response("400 Bad Request", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]
        pair_dir = _pair_output_dir(old_tag, new_tag)
        os.makedirs(pair_dir, exist_ok=True)
        try:
            run_diff(
                old_tag=old_tag,
                new_tag=new_tag,
                verify_ssl=DEFAULT_VERIFY_SSL,
                output_dir=pair_dir,
                summary=True,
                only_removed=False,
                winscp=True,
                cache_dir=CACHE_DIR,
            )
            location = f"/result?old={quote(old_tag, safe='')}&new={quote(new_tag or '', safe='')}&generated=1"
            start_response("303 See Other", [("Location", location)])
            return [b""]
        except Exception as exc:
            _log_exception("Failed to generate diff", exc)
            body = _render_layout(content=_render_error(GENERIC_ERROR_MESSAGE), releases=releases, message=error)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

    if path == "/result" and method == "GET":
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        old_tag = (params.get("old") or [""])[0].strip()
        new_tag = (params.get("new") or [""])[0].strip() or None
        auto_scroll = (params.get("generated") or ["0"])[0] == "1"
        if not old_tag:
            start_response("400 Bad Request", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Missing old tag"]
        try:
            result = run_diff(
                old_tag=old_tag,
                new_tag=new_tag,
                verify_ssl=DEFAULT_VERIFY_SSL,
                output_dir=_pair_output_dir(old_tag, new_tag),
                summary=True,
                only_removed=False,
                winscp=True,
                cache_dir=CACHE_DIR,
            )
            body = _render_result(result, releases=releases, auto_scroll=auto_scroll)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]
        except Exception as exc:
            _log_exception("Failed to load result", exc)
            body = _render_layout(content=_render_error(GENERIC_ERROR_MESSAGE), releases=releases, message=error)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

    if path.startswith("/download/") and method == "GET":
        parts = path.split("/", 3)
        if len(parts) != 4:
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        rel_dir = unquote(parts[2])
        rel_name = unquote(parts[3])
        return _serve_file(environ, start_response, OUTPUT_DIR, rel_dir, rel_name, attachment=True)

    if path.startswith("/view/") and method == "GET":
        parts = path.split("/", 3)
        if len(parts) != 4:
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        rel_dir = unquote(parts[2])
        rel_name = unquote(parts[3])
        back_url = (params.get("return_to") or [""])[0].strip()
        try:
            target = _safe_served_path(OUTPUT_DIR, rel_dir, rel_name)
        except ValueError:
            start_response("403 Forbidden", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Forbidden"]
        if not os.path.isfile(target):
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        body = _render_text_view(target, os.path.basename(target), back_url=back_url)
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [body.encode("utf-8")]

    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return [b"Not found"]


def _render_error(message):
    return f'<div class="notice" style="border-color: rgba(217,119,6,.5);">{_escape(message)}</div>'


def _log_exception(context, exc):
    print(f"{context}: {exc}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the YOURLS-diff web application.")
    parser.add_argument("--host", default=os.environ.get("YOURLS_DIFF_HOST", "0.0.0.0"))
    parser.add_argument("--port", default=int(os.environ.get("YOURLS_DIFF_PORT", "8000")), type=int)
    args = parser.parse_args(argv)

    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with make_server(args.host, args.port, app, server_class=ThreadingWSGIServer, handler_class=WSGIRequestHandler) as httpd:
        print(f"Serving YOURLS-diff on http://{args.host}:{args.port}")
        print(f"Cache directory: {CACHE_DIR}")
        print(f"Output directory: {OUTPUT_DIR}")
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
