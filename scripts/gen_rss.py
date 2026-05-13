#!/usr/bin/env python3
"""Generate daily HTML pages + RSS feed for Arxiv Daily.

Goal (Folo-friendly): item click should show the full content in-reader.
So we put the full daily body into <description> (and mirror in <content:encoded>),
while still keeping <link> to the standalone HTML page.

Data source:
  /Volumes/Extra/agnet_workspace/arxiv_daily/YYYY-MM-DD/reviews/screening.json

Output structure under site root:
  index.html
  feed.xml
  days/YYYY-MM-DD.html

Strategy:
  - Generate one standalone HTML page per day
  - RSS item links to that day's HTML page
  - RSS item description/content:encoded contains FULL daily content (reader renders it)
  - Keep RSS tags conservative, avoid styles/details.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path('/Volumes/Extra/agnet_workspace/arxiv_daily')
SITE_LINK_DEFAULT = 'https://desperadoccy.github.io/Arxiv-daily/'
CST = dt.timezone(dt.timedelta(hours=8))


def _today() -> dt.date:
    return dt.date.today()


def _safe(s: str) -> str:
    return html.escape(s, quote=True)


def _fmt_rfc2822(d: dt.date) -> str:
    dt_ = dt.datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=CST)
    return dt_.strftime('%a, %d %b %Y %H:%M:%S %z')


def _load_screening(day_dir: Path) -> Optional[List[Dict[str, Any]]]:
    p = day_dir / 'reviews' / 'screening.json'
    if not p.exists():
        return None
    with p.open('r', encoding='utf-8') as f:
        data = json.load(f)
    return data if isinstance(data, list) else None


def _pick_deep_text(item: Dict[str, Any]) -> Optional[Dict[str, str]]:
    deep = item.get('deep_review')
    if not isinstance(deep, dict):
        return None
    for k in ('codex', 'gemini'):
        v = deep.get(k)
        if isinstance(v, dict):
            out = {}
            for key in ('innovation', 'method', 'experiments', 'reason'):
                val = v.get(key)
                if isinstance(val, str) and val.strip():
                    out[key] = val.strip()
            if out:
                return out
    return None


def _group_items(screening: List[Dict[str, Any]]):
    must, rec, skip = [], [], []
    for it in screening:
        try:
            level = it['screening']['level']
        except Exception:
            continue
        if level == '必读':
            must.append(it)
        elif level == '推荐':
            rec.append(it)
        else:
            skip.append(it)
    return must, rec, skip


def _paper_title(it: Dict[str, Any]) -> str:
    return str(it.get('paper', {}).get('title', '')).strip()


def _paper_url(it: Dict[str, Any]) -> str:
    return str(it.get('paper', {}).get('url', '')).strip()


def _paper_summary(it: Dict[str, Any]) -> str:
    return str(it.get('screening', {}).get('summary', '')).strip()


def _paper_reason(it: Dict[str, Any]) -> str:
    return str(it.get('screening', {}).get('reason', '')).strip()


def _paper_direction(it: Dict[str, Any]) -> str:
    return str(it.get('screening', {}).get('direction', '')).strip()


def _paper_tags(it: Dict[str, Any]) -> List[str]:
    tags = it.get('paper', {}).get('tags') or []
    return [str(t) for t in tags] if isinstance(tags, list) else []


def _render_paper_full_html(it: Dict[str, Any], include_deep: bool) -> str:
    """Conservative HTML snippet for one paper."""
    title = _paper_title(it)
    url = _paper_url(it)
    direction = _paper_direction(it)
    tags = _paper_tags(it)
    summary = _paper_summary(it)
    reason = _paper_reason(it)
    deep = _pick_deep_text(it) if include_deep else None

    parts = ['<li>']
    if url:
        parts.append(f'<p><strong><a href="{_safe(url)}">{_safe(title)}</a></strong></p>')
    else:
        parts.append(f'<p><strong>{_safe(title)}</strong></p>')

    meta = []
    if direction:
        meta.append(f'方向: {_safe(direction)}')
    if tags:
        meta.append('标签: ' + ' '.join(f'[{_safe(t)}]' for t in tags))
    if meta:
        parts.append('<p>' + ' | '.join(meta) + '</p>')

    if summary:
        parts.append(f'<p><strong>简述</strong>: {_safe(summary)}</p>')
    if reason:
        parts.append(f'<p><strong>筛选理由</strong>: {_safe(reason)}</p>')

    if deep:
        parts.append('<p><strong>Deep Review</strong></p>')
        if deep.get('innovation'):
            parts.append(f'<p><strong>创新</strong>: {_safe(deep["innovation"])}</p>')
        if deep.get('method'):
            parts.append(f'<p><strong>方法</strong>: {_safe(deep["method"])}</p>')
        if deep.get('experiments'):
            parts.append(f'<p><strong>实验</strong>: {_safe(deep["experiments"])}</p>')
        if deep.get('reason'):
            parts.append(f'<p><strong>Deep理由</strong>: {_safe(deep["reason"])}</p>')

    parts.append('</li>')
    return ''.join(parts)


def _render_day_full_html(day: dt.date, screening: List[Dict[str, Any]], site_link: str) -> str:
    """FULL daily body HTML used inside RSS item."""
    must, rec, skip = _group_items(screening)
    day_url = f'{site_link}days/{day.isoformat()}.html'

    parts = []
    parts.append(f'<p><strong>ArXiv Daily · {day.isoformat()}</strong></p>')
    parts.append(f'<p>共 {len(screening)} 篇，🔴 必读 {len(must)}，🟡 推荐 {len(rec)}，⚪ 可跳过 {len(skip)}。</p>')
    parts.append(f'<p>原网页版本: <a href="{_safe(day_url)}">{_safe(day_url)}</a></p>')

    if must:
        parts.append(f'<p><strong>🔴 必读（{len(must)}）</strong></p>')
        parts.append('<ul>')
        parts.extend(_render_paper_full_html(it, include_deep=True) for it in must)
        parts.append('</ul>')

    if rec:
        parts.append(f'<p><strong>🟡 推荐（{len(rec)}）</strong></p>')
        parts.append('<ul>')
        parts.extend(_render_paper_full_html(it, include_deep=True) for it in rec)
        parts.append('</ul>')

    if skip:
        parts.append(f'<p><strong>⚪ 可跳过（{len(skip)}）</strong></p>')
        parts.append('<ul>')
        for it in skip[:20]:
            title = _paper_title(it)
            reason = _paper_reason(it)
            txt = _safe(title) + (f'（{_safe(reason)}）' if reason else '')
            parts.append(f'<li>{txt}</li>')
        parts.append('</ul>')
        if len(skip) > 20:
            parts.append(f'<p>其余 {len(skip) - 20} 篇略。</p>')

    return ''.join(parts)


def _render_paper_card(it: Dict[str, Any]) -> str:
    title = _paper_title(it)
    url = _paper_url(it)
    tags = _paper_tags(it)
    direction = _paper_direction(it)
    summary = _paper_summary(it)
    reason = _paper_reason(it)
    deep = _pick_deep_text(it)

    parts = ['<article class="paper">']
    parts.append(f'<h3><a href="{_safe(url)}" target="_blank" rel="noopener noreferrer">{_safe(title)}</a></h3>')
    meta = []
    if direction:
        meta.append(f'方向: {_safe(direction)}')
    if tags:
        meta.append('标签: ' + ' '.join(f'<span class="tag">{_safe(str(t))}</span>' for t in tags))
    if meta:
        parts.append('<p class="meta">' + ' | '.join(meta) + '</p>')
    if summary:
        parts.append(f'<p><strong>简述</strong>: {_safe(summary)}</p>')
    if reason:
        parts.append(f'<p><strong>筛选理由</strong>: {_safe(reason)}</p>')
    if deep:
        parts.append('<section class="deep">')
        parts.append('<p class="deep-title">Deep Review</p>')
        if deep.get('innovation'):
            parts.append(f'<p><strong>创新</strong>: {_safe(deep["innovation"])}</p>')
        if deep.get('method'):
            parts.append(f'<p><strong>方法</strong>: {_safe(deep["method"])}</p>')
        if deep.get('experiments'):
            parts.append(f'<p><strong>实验</strong>: {_safe(deep["experiments"])}</p>')
        if deep.get('reason'):
            parts.append(f'<p><strong>Deep理由</strong>: {_safe(deep["reason"])}</p>')
        parts.append('</section>')
    parts.append('</article>')
    return '\n'.join(parts)


def _render_day_page(day: dt.date, screening: List[Dict[str, Any]]) -> str:
    must, rec, skip = _group_items(screening)
    title = f'ArXiv Daily · {day.isoformat()}'
    nav = '<p><a href="../index.html">← 返回索引</a> | <a href="../feed.xml">RSS</a></p>'

    sections = []
    if must:
        sections.append(f'<section><h2>🔴 必读（{len(must)}）</h2>' + ''.join(_render_paper_card(it) for it in must) + '</section>')
    if rec:
        sections.append(f'<section><h2>🟡 推荐（{len(rec)}）</h2>' + ''.join(_render_paper_card(it) for it in rec) + '</section>')
    if skip:
        items = []
        for it in skip[:20]:
            title_i = _paper_title(it)
            reason_i = _paper_reason(it)
            items.append(f'<li>{_safe(title_i)}' + (f'（{_safe(reason_i)}）' if reason_i else '') + '</li>')
        tail = f'<p>其余 {len(skip) - 20} 篇略。</p>' if len(skip) > 20 else ''
        sections.append(f'<section><h2>⚪ 可跳过（{len(skip)}）</h2><ul>{"".join(items)}</ul>{tail}</section>')

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_safe(title)}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f5f7fb; color: #1f2328; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1 {{ margin-bottom: 8px; }}
    h2 {{ margin-top: 36px; border-bottom: 1px solid #d8dee4; padding-bottom: 8px; }}
    .summary {{ color: #57606a; margin-bottom: 20px; }}
    .paper {{ background: #fff; border: 1px solid #d8dee4; border-radius: 14px; padding: 18px 18px 12px; margin: 14px 0; box-shadow: 0 1px 2px rgba(31,35,40,.04); }}
    .paper h3 {{ margin: 0 0 10px; font-size: 18px; line-height: 1.45; }}
    .paper p {{ line-height: 1.7; margin: 8px 0; }}
    .meta {{ color: #57606a; font-size: 14px; }}
    .tag {{ display: inline-block; padding: 1px 8px; margin-right: 4px; background: #eef2ff; color: #3b5bdb; border-radius: 999px; font-size: 12px; }}
    .deep {{ margin-top: 12px; padding: 12px 14px; background: #f8fafc; border-left: 3px solid #8b949e; border-radius: 8px; }}
    .deep-title {{ font-weight: 700; margin-top: 0; }}
    a {{ color: #0969da; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    {nav}
    <h1>{_safe(title)}</h1>
    <p class="summary">共 {len(screening)} 篇。🔴 必读 {len(must)}，🟡 推荐 {len(rec)}，⚪ 可跳过 {len(skip)}。</p>
    {''.join(sections)}
  </main>
</body>
</html>
'''


def _render_index(days: List[Tuple[dt.date, List[Dict[str, Any]]]]) -> str:
    items = []
    for day, screening in days:
        must, rec, skip = _group_items(screening)
        items.append(f'<li><a href="days/{day.isoformat()}.html">{day.isoformat()}</a> · 共 {len(screening)} 篇，必读 {len(must)}，推荐 {len(rec)}，可跳过 {len(skip)}</li>')

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ArXiv Daily</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; background: #f5f7fb; color: #1f2328; }}
    .card {{ background: #fff; border: 1px solid #d8dee4; border-radius: 16px; padding: 20px; }}
    li {{ margin: 10px 0; line-height: 1.7; }}
    a {{ color: #0969da; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>ArXiv Daily</h1>
    <p><a href="feed.xml">订阅 RSS</a></p>
    <ul>
      {''.join(items)}
    </ul>
  </div>
</body>
</html>
'''


def _render_rss(title: str, site_link: str, desc: str, days: List[Tuple[dt.date, List[Dict[str, Any]]]]) -> str:
    now = dt.datetime.now().astimezone(CST).replace(microsecond=0).strftime('%a, %d %b %Y %H:%M:%S %z')
    self_feed = site_link + 'feed.xml'
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        '<channel>',
        f'  <title>{_safe(title)}</title>',
        f'  <description>{_safe(desc)}</description>',
        f'  <link>{_safe(site_link)}</link>',
        f'  <atom:link href="{_safe(self_feed)}" rel="self" type="application/rss+xml" />',
        f'  <lastBuildDate>{_safe(now)}</lastBuildDate>',
        '  <language>zh-cn</language>',
    ]
    for day, screening in days:
        item_link = f'{site_link}days/{day.isoformat()}.html'
        full_html = _render_day_full_html(day, screening, site_link)
        out.extend([
            '  <item>',
            f'    <title>{_safe("ArXiv Daily · " + day.isoformat())}</title>',
            f'    <link>{_safe(item_link)}</link>',
            f'    <guid isPermaLink="true">{_safe(item_link)}</guid>',
            f'    <pubDate>{_safe(_fmt_rfc2822(day))}</pubDate>',
            f'    <description><![CDATA[{full_html}]]></description>',
            f'    <content:encoded><![CDATA[{full_html}]]></content:encoded>',
            '  </item>',
        ])
    out.extend(['</channel>', '</rss>'])
    return '\n'.join(out) + '\n'


def generate_site(days: int, out_dir: Path, site_link: str, title: str, desc: str) -> None:
    today = _today()
    day_records: List[Tuple[dt.date, List[Dict[str, Any]]]] = []
    for i in range(days):
        day = today - dt.timedelta(days=i)
        screening = _load_screening(BASE / day.isoformat())
        if screening:
            day_records.append((day, screening))
    day_records.sort(key=lambda x: x[0], reverse=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    days_dir = out_dir / 'days'
    days_dir.mkdir(parents=True, exist_ok=True)

    for day, screening in day_records:
        (days_dir / f'{day.isoformat()}.html').write_text(_render_day_page(day, screening), encoding='utf-8')

    (out_dir / 'index.html').write_text(_render_index(day_records), encoding='utf-8')
    (out_dir / 'feed.xml').write_text(_render_rss(title, site_link, desc, day_records), encoding='utf-8')
    print(f'Generated site in {out_dir} with {len(day_records)} days')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--title', default='ArXiv Daily (AI Review)')
    ap.add_argument('--link', default=SITE_LINK_DEFAULT)
    ap.add_argument('--desc', default='Daily arXiv screening + deep reviews (full content in RSS items).')
    args = ap.parse_args()
    generate_site(args.days, args.out_dir, args.link, args.title, args.desc)


if __name__ == '__main__':
    main()
