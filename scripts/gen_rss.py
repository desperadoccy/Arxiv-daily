#!/usr/bin/env python3
"""Generate daily HTML pages + RSS feed for Arxiv Daily.

Data source:
  /Volumes/Extra/arxiv_daily/YYYY-MM-DD/reviews/screening.json

Output structure under site root:
  index.html
  feed.xml
  days/YYYY-MM-DD.html

Strategy:
  - Generate one standalone HTML page per day
  - RSS item links to that day's HTML page
  - RSS description stays plain text for reader compatibility
  - content:encoded provides a compact rich summary
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path('/Volumes/Extra/arxiv_daily')
SITE_LINK = 'https://desperadoccy.github.io/Arxiv-daily/'


def _today() -> dt.date:
    return dt.date.today()


def _safe(s: str) -> str:
    return html.escape(s, quote=True)


def _fmt_rfc2822(d: dt.date) -> str:
    dt_ = dt.datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=dt.timezone.utc)
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


def _render_paper_text(it: Dict[str, Any], include_deep: bool) -> str:
    paper = it.get('paper', {})
    scr = it.get('screening', {})
    title = str(paper.get('title', '')).strip()
    url = str(paper.get('url', '')).strip()
    tags = paper.get('tags') or []
    if not isinstance(tags, list):
        tags = []
    summary = str(scr.get('summary', '')).strip()
    reason = str(scr.get('reason', '')).strip()
    direction = str(scr.get('direction', '')).strip()

    lines = []
    if title:
        lines.append(f'- {title}')
    meta = []
    if direction:
        meta.append(f'方向:{direction}')
    if tags:
        meta.append('标签:' + ','.join(str(t) for t in tags))
    if meta:
        lines.append('  ' + ' | '.join(meta))
    if url:
        lines.append(f'  链接: {url}')
    if summary:
        lines.append(f'  简述: {summary}')
    if reason:
        lines.append(f'  筛选理由: {reason}')
    if include_deep:
        deep = _pick_deep_text(it)
        if deep:
            lines.append('  Deep Review:')
            if deep.get('innovation'):
                lines.append('    创新: ' + deep['innovation'])
            if deep.get('method'):
                lines.append('    方法: ' + deep['method'])
            if deep.get('experiments'):
                lines.append('    实验: ' + deep['experiments'])
            if deep.get('reason'):
                lines.append('    Deep理由: ' + deep['reason'])
    return '\n'.join(lines)


def _render_day_text(day: dt.date, screening: List[Dict[str, Any]], site_link: str) -> str:
    must, rec, skip = _group_items(screening)
    day_url = f'{site_link}days/{day.isoformat()}.html'
    lines = [
        f'ArXiv Daily · {day.isoformat()}',
        f'共 {len(screening)} 篇。必读 {len(must)}，推荐 {len(rec)}，可跳过 {len(skip)}。',
        f'完整网页: {day_url}',
    ]

    preview = (must + rec)[:5]
    if preview:
        lines.append('')
        lines.append('【重点论文】')
        for it in preview:
            lines.append(_render_paper_text(it, include_deep=False))

    return '\n'.join(lines).strip()


def _render_paper_card(it: Dict[str, Any]) -> str:
    paper = it.get('paper', {})
    scr = it.get('screening', {})
    title = str(paper.get('title', ''))
    url = str(paper.get('url', ''))
    tags = paper.get('tags') or []
    if not isinstance(tags, list):
        tags = []
    direction = str(scr.get('direction', ''))
    summary = str(scr.get('summary', ''))
    reason = str(scr.get('reason', ''))
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


def _render_day_page(day: dt.date, screening: List[Dict[str, Any]], site_link: str) -> str:
    must, rec, skip = _group_items(screening)
    title = f'ArXiv Daily · {day.isoformat()}'
    nav = '<p><a href="../index.html">← 返回索引</a> | <a href="../feed.xml">RSS</a></p>'

    sections = []
    if must:
        sections.append(f'<section><h2>🔴 必读（{len(must)}）</h2>' + ''.join(_render_paper_card(it) for it in must) + '</section>')
    if rec:
        sections.append(f'<section><h2>🟡 推荐（{len(rec)}）</h2>' + ''.join(_render_paper_card(it) for it in rec) + '</section>')
    if skip:
        items = ''.join(f'<li>{_safe(str(it.get("paper", {}).get("title", "")))}' + (f'（{_safe(str(it.get("screening", {}).get("reason", ""))) }）' if str(it.get('screening', {}).get('reason', '')).strip() else '') + '</li>' for it in skip[:20])
        tail = f'<p>其余 {len(skip) - 20} 篇略。</p>' if len(skip) > 20 else ''
        sections.append(f'<section><h2>⚪ 可跳过（{len(skip)}）</h2><ul>{items}</ul>{tail}</section>')

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


def _render_index(days: List[Tuple[dt.date, List[Dict[str, Any]]]], site_link: str) -> str:
    items = []
    for day, screening in days:
        must, rec, skip = _group_items(screening)
        items.append(
            f'<li><a href="days/{day.isoformat()}.html">{day.isoformat()}</a> · 共 {len(screening)} 篇，必读 {len(must)}，推荐 {len(rec)}，可跳过 {len(skip)}</li>'
        )

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
    now = dt.datetime.now(dt.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %z')
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        '<channel>',
        f'  <title>{_safe(title)}</title>',
        f'  <link>{_safe(site_link)}</link>',
        f'  <description>{_safe(desc)}</description>',
        f'  <lastBuildDate>{_safe(now)}</lastBuildDate>',
        '  <language>zh-cn</language>',
    ]
    for day, screening in days:
        item_link = f'{site_link}days/{day.isoformat()}.html'
        body_text = _render_day_text(day, screening, site_link)
        must, rec, skip = _group_items(screening)
        body_html = (
            f'<p><b>ArXiv Daily · {day.isoformat()}</b></p>'
            f'<p>共 {len(screening)} 篇。🔴 必读 {len(must)}，🟡 推荐 {len(rec)}，⚪ 可跳过 {len(skip)}。</p>'
            f'<p>完整网页: <a href="{_safe(item_link)}">{_safe(item_link)}</a></p>'
        )
        out.extend([
            '  <item>',
            f'    <title>{_safe("ArXiv Daily · " + day.isoformat())}</title>',
            f'    <link>{_safe(item_link)}</link>',
            f'    <guid isPermaLink="true">{_safe(item_link)}</guid>',
            f'    <pubDate>{_safe(_fmt_rfc2822(day))}</pubDate>',
            '    <description><![CDATA[' + body_text + ']]></description>',
            '    <content:encoded><![CDATA[' + body_html + ']]></content:encoded>',
            '  </item>',
        ])
    out.extend(['</channel>', '</rss>'])
    return '\n'.join(out) + '\n'


def generate_site(days: int, out_dir: Path, site_link: str, title: str, desc: str) -> None:
    today = _today()
    day_records: List[Tuple[dt.date, List[Dict[str, Any]]]] = []
    for i in range(1, days + 1):
        day = today - dt.timedelta(days=i)
        screening = _load_screening(BASE / day.isoformat())
        if screening:
            day_records.append((day, screening))
    day_records.sort(key=lambda x: x[0], reverse=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    days_dir = out_dir / 'days'
    days_dir.mkdir(parents=True, exist_ok=True)

    for day, screening in day_records:
        (days_dir / f'{day.isoformat()}.html').write_text(_render_day_page(day, screening, site_link), encoding='utf-8')

    (out_dir / 'index.html').write_text(_render_index(day_records, site_link), encoding='utf-8')
    (out_dir / 'feed.xml').write_text(_render_rss(title, site_link, desc, day_records), encoding='utf-8')

    print(f'Generated site in {out_dir} with {len(day_records)} days')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--title', default='ArXiv Daily (AI Review)')
    ap.add_argument('--link', default=SITE_LINK)
    ap.add_argument('--desc', default='Daily arXiv screening + deep reviews, with standalone HTML pages.')
    args = ap.parse_args()
    generate_site(args.days, args.out_dir, args.link, args.title, args.desc)


if __name__ == '__main__':
    main()
