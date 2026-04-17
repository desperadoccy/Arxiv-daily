#!/usr/bin/env python3
"""Generate a single-item-per-day RSS feed from arxiv_daily outputs.

Data source:
  /Volumes/Extra/arxiv_daily/YYYY-MM-DD/reviews/screening.json
  /Volumes/Extra/arxiv_daily/YYYY-MM-DD/reviews/deep/*.json (optional)

Feed strategy:
  - Keep last N days (default 7)
  - One RSS item per day

Behavior:
  - If a paper has `deep_review`, include it in the RSS content for both 必读 and 推荐.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path('/Volumes/Extra/arxiv_daily')


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


def _render_paper(it: Dict[str, Any], with_deep: bool) -> str:
    paper = it.get('paper', {})
    scr = it.get('screening', {})
    title = str(paper.get('title', ''))
    url = str(paper.get('url', ''))
    tags = paper.get('tags') or []
    if not isinstance(tags, list):
        tags = []
    summary = str(scr.get('summary', ''))
    reason = str(scr.get('reason', ''))
    direction = str(scr.get('direction', ''))

    parts = [f'<li><p><b>{_safe(title)}</b></p>']
    meta = []
    if direction:
        meta.append(f'方向: {_safe(direction)}')
    if tags:
        meta.append('标签: ' + ' '.join(f'[{_safe(str(t))}]' for t in tags))
    if url:
        meta.append(f'链接: <a href="{_safe(url)}">{_safe(url)}</a>')
    if meta:
        parts.append('<p>' + ' | '.join(meta) + '</p>')
    if summary:
        parts.append(f'<p><b>简述</b>: {_safe(summary)}</p>')
    if reason:
        parts.append(f'<p><b>筛选理由</b>: {_safe(reason)}</p>')
    if with_deep:
        deep = _pick_deep_text(it)
        if deep:
            parts.append('<div style="margin: 8px 0 0 0; padding: 8px 10px; border-left: 3px solid #d0d7de; background: #f6f8fa;">')
            parts.append('<p><b>Deep Review</b></p>')
            if deep.get('innovation'):
                parts.append(f'<p><b>创新</b>: {_safe(deep["innovation"])}</p>')
            if deep.get('method'):
                parts.append(f'<p><b>方法</b>: {_safe(deep["method"])}</p>')
            if deep.get('experiments'):
                parts.append(f'<p><b>实验</b>: {_safe(deep["experiments"])}</p>')
            if deep.get('reason'):
                parts.append(f'<p><b>Deep 理由</b>: {_safe(deep["reason"])}</p>')
            parts.append('</div>')
    parts.append('</li>')
    return '\n'.join(parts)


def _render_day_html(day: dt.date, screening: List[Dict[str, Any]]) -> str:
    must, rec, skip = _group_items(screening)
    parts = []
    parts.append(f'<h2>ArXiv Daily · {day.isoformat()}</h2>')
    parts.append(f'<p>共 {len(screening)} 篇。🔴 必读 {len(must)}，🟡 推荐 {len(rec)}，⚪ 可跳过 {len(skip)}。</p>')
    if must:
        parts.append(f'<h3>🔴 必读（{len(must)}）</h3><ol>')
        parts.extend(_render_paper(it, True) for it in must)
        parts.append('</ol>')
    if rec:
        parts.append(f'<h3>🟡 推荐（{len(rec)}）</h3><ol>')
        parts.extend(_render_paper(it, True) for it in rec)
        parts.append('</ol>')
    if skip:
        parts.append(f'<h3>⚪ 可跳过（{len(skip)}）</h3><ul>')
        for it in skip[:10]:
            paper = it.get('paper', {})
            scr = it.get('screening', {})
            title = str(paper.get('title', ''))
            reason = str(scr.get('reason', ''))
            text = _safe(title) + (f'（{_safe(reason)}）' if reason else '')
            parts.append(f'<li>{text}</li>')
        parts.append('</ul>')
        if len(skip) > 10:
            parts.append(f'<p>其余 {len(skip) - 10} 篇略。</p>')
    return '\n'.join(parts)


def build_items(days: int):
    today = _today()
    items = []
    for i in range(1, days + 1):
        day = today - dt.timedelta(days=i)
        screening = _load_screening(BASE / day.isoformat())
        if screening:
            items.append((day, _render_day_html(day, screening)))
    items.sort(key=lambda x: x[0], reverse=True)
    return items


def render_rss(title: str, link: str, desc: str, items):
    now = dt.datetime.now(dt.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %z')
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '<channel>',
        f'  <title>{_safe(title)}</title>',
        f'  <link>{_safe(link)}</link>',
        f'  <description>{_safe(desc)}</description>',
        f'  <lastBuildDate>{_safe(now)}</lastBuildDate>',
        '  <language>zh-cn</language>',
    ]
    for day, body in items:
        out.extend([
            '  <item>',
            f'    <title>{_safe("ArXiv Daily · " + day.isoformat())}</title>',
            f'    <link>{_safe(link)}</link>',
            f'    <guid isPermaLink="false">{_safe("arxiv-daily:" + day.isoformat())}</guid>',
            f'    <pubDate>{_safe(_fmt_rfc2822(day))}</pubDate>',
            f'    <description><![CDATA[{body}]]></description>',
            '  </item>',
        ])
    out.extend(['</channel>', '</rss>'])
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--title', default='ArXiv Daily (AI Review)')
    ap.add_argument('--link', default='https://desperadoccy.github.io/Arxiv-daily/')
    ap.add_argument('--desc', default='Daily arXiv screening + deep reviews (one item per day).')
    args = ap.parse_args()
    rss = render_rss(args.title, args.link, args.desc, build_items(args.days))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rss, encoding='utf-8')
    print(f'Wrote {args.out}')


if __name__ == '__main__':
    main()
