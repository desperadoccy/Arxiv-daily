#!/usr/bin/env python3
"""Generate daily HTML pages + RSS feed for Arxiv Daily.

Goal (Folo-friendly): item click should show the full content in-reader.
So we put the full daily body into <description> (and mirror in <content:encoded>),
while still keeping <link> to the standalone HTML page.

Data source:
  /Volumes/Extra/agent_workspace/arxiv_daily/YYYY-MM-DD/reviews/screening.json

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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path('/Volumes/Extra/agent_workspace/arxiv_daily')
SITE_LINK_DEFAULT = 'https://desperadoccy.github.io/Arxiv-daily/'
CST = dt.timezone(dt.timedelta(hours=8))


def _today() -> dt.date:
    return dt.date.today()


def _safe(s: str) -> str:
    return html.escape(s, quote=True)


def _paragraphs_html(text: str) -> str:
    paragraphs = []
    for block in text.split('\n\n'):
        block = block.strip()
        if not block:
            continue
        paragraphs.append(f'<p>{_safe(block).replace(chr(10), "<br />")}</p>')
    return ''.join(paragraphs)


def _inline_markdown_html(text: str) -> str:
    escaped = _safe(text)
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)


def _markdownish_html(text: str) -> str:
    """Small Markdown subset for model output inside RSS/HTML pages."""
    out: List[str] = []
    list_items: List[str] = []
    para: List[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append('<p>' + '<br />'.join(_inline_markdown_html(line) for line in para) + '</p>')
            para = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            out.append('<ul>' + ''.join(f'<li>{item}</li>' for item in list_items) + '</ul>')
            list_items = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_para()
            flush_list()
            continue
        if line.startswith('>'):
            line = line.lstrip('> ').strip()
        if line.startswith('### '):
            flush_para()
            flush_list()
            out.append(f'<h4>{_inline_markdown_html(line[4:].strip())}</h4>')
        elif line.startswith('## '):
            flush_para()
            flush_list()
            out.append(f'<h4>{_inline_markdown_html(line[3:].strip())}</h4>')
        elif line.startswith('- '):
            flush_para()
            list_items.append(_inline_markdown_html(line[2:].strip()))
        else:
            flush_list()
            para.append(line)

    flush_para()
    flush_list()
    return ''.join(out)


def _fmt_rfc2822(d: dt.date) -> str:
    dt_ = dt.datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=CST)
    dt_ = min(dt_, dt.datetime.now(CST))
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

    analysis = deep.get('analysis')
    if isinstance(analysis, str) and analysis.strip():
        return {'analysis': analysis.strip()}

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
    out = {}
    for key in ('innovation', 'method', 'experiments', 'reason'):
        val = deep.get(key)
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
    screen = it.get('screening', {})
    return str(screen.get('final_rating_reason') or screen.get('reason', '')).strip()


def _paper_direction(it: Dict[str, Any]) -> str:
    return str(it.get('screening', {}).get('direction', '')).strip()


def _paper_tags(it: Dict[str, Any]) -> List[str]:
    tags = it.get('paper', {}).get('tags') or []
    return [str(t) for t in tags] if isinstance(tags, list) else []


def _paper_authors_text(it: Dict[str, Any]) -> str:
    return str(it.get('paper', {}).get('authors', '')).strip()


def _paper_author_info(it: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    info = it.get('author_info')
    if isinstance(info, dict):
        return info
    paper_info = it.get('paper', {}).get('author_info')
    return paper_info if isinstance(paper_info, dict) else None


def _paper_authors_html(it: Dict[str, Any]) -> str:
    info = _paper_author_info(it)
    if not isinstance(info, dict):
        return _safe(_paper_authors_text(it))

    authors = info.get('authors')
    if not isinstance(authors, list):
        return _safe(_paper_authors_text(it))

    parts = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = str(author.get('name', '')).strip()
        affiliation = str(author.get('affiliation', '')).strip()
        if not name:
            continue
        if affiliation:
            parts.append(f'{_safe(name)} <span class="affiliation">({_safe(affiliation)})</span>')
        else:
            parts.append(_safe(name))
    return '; '.join(parts) or _safe(_paper_authors_text(it))


def _render_paper_full_html(it: Dict[str, Any], include_deep: bool) -> str:
    """Conservative HTML snippet for one paper."""
    title = _paper_title(it)
    url = _paper_url(it)
    authors = _paper_authors_html(it)
    direction = _paper_direction(it)
    tags = _paper_tags(it)
    summary = _paper_summary(it)
    reason = _paper_reason(it)
    deep = _pick_deep_text(it) if include_deep else None

    parts = ['<article class="paper-item" style="margin:18px 0;padding:14px 0;border-top:1px solid #d8dee4;">']
    if url:
        parts.append(f'<h3><a href="{_safe(url)}">{_safe(title)}</a></h3>')
    else:
        parts.append(f'<h3>{_safe(title)}</h3>')

    if authors:
        parts.append(f'<p><strong>作者</strong>: {authors}</p>')

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

    if it.get('reading_focus'):
        parts.append(f'<p><strong>阅读重点</strong>: {_safe(it["reading_focus"])}</p>')

    if deep:
        parts.append('<section class="deep-review" style="margin-top:12px;padding:12px 14px;background:#f8fafc;border-left:3px solid #8b949e;"><h4>Deep Review</h4>')
        if deep.get('analysis'):
            parts.append(_markdownish_html(deep['analysis']))
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
    return ''.join(parts)


def _render_day_full_html(day: dt.date, screening: List[Dict[str, Any]], site_link: str) -> str:
    """FULL daily body HTML used inside RSS item."""
    must, rec, skip = _group_items(screening)
    day_url = f'{site_link}days/{day.isoformat()}.html'

    parts = []
    parts.append(f'<p><strong>ArXiv Daily · {day.isoformat()}</strong></p>')
    parts.append(f'<p>共 {len(screening)} 篇，🔴 必读 {len(must)}，🟡 推荐 {len(rec)}，⚪ 可跳过 {len(skip)}。</p>')
    parts.append(f'<p>原网页版本: <a href="{_safe(day_url)}">{_safe(day_url)}</a></p>')
    digest = _load_digest(day)
    if digest:
        parts.append(_digest_intro(digest, day, site_link))

    if must:
        parts.append(f'<p><strong>🔴 必读（{len(must)}）</strong></p>')
        parts.extend(_render_paper_full_html(it, include_deep=True) for it in must)

    if rec:
        parts.append(f'<p><strong>🟡 推荐（{len(rec)}）</strong></p>')
        parts.extend(_render_paper_full_html(it, include_deep=True) for it in rec)

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
    authors = _paper_authors_html(it)
    tags = _paper_tags(it)
    direction = _paper_direction(it)
    summary = _paper_summary(it)
    reason = _paper_reason(it)
    deep = _pick_deep_text(it)

    parts = ['<article class="paper">']
    parts.append(f'<h3><a href="{_safe(url)}" target="_blank" rel="noopener noreferrer">{_safe(title)}</a></h3>')
    if authors:
        parts.append(f'<p class="authors"><strong>作者</strong>: {authors}</p>')
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
    if it.get('reading_focus'):
        parts.append(f'<p><strong>阅读重点</strong>: {_safe(it["reading_focus"])}</p>')
    if deep:
        parts.append('<section class="deep">')
        parts.append('<p class="deep-title">Deep Review</p>')
        if deep.get('analysis'):
            parts.append(_markdownish_html(deep['analysis']))
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


def _render_day_page(day: dt.date, screening: List[Dict[str, Any]], full_archive=False) -> str:
    must, rec, skip = _group_items(screening)
    title = f'ArXiv Daily · {day.isoformat()}'
    nav = '<p><a href="../index.html">← 返回索引</a> | <a href="../feed.xml">RSS</a></p>'

    sections = []
    digest = _load_digest(day)
    if digest:
        sections.append(_digest_intro(digest, day, SITE_LINK_DEFAULT))
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

    if full_archive:
        sections = ([ _digest_intro(digest, day, SITE_LINK_DEFAULT) ] if digest else [])
        sections.append('<section><h2>全部全文评审</h2>' + ''.join(_render_paper_card(item) for item in screening) + '</section>')

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
    .authors {{ color: #24292f; font-size: 14px; }}
    .affiliation {{ color: #57606a; }}
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
    last_build = dt.datetime.now(CST).strftime('%a, %d %b %Y %H:%M:%S %z')
    self_feed = site_link + 'feed.xml'
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        '<channel>',
        f'  <title>{_safe(title)}</title>',
        f'  <description>{_safe(desc)}</description>',
        f'  <link>{_safe(site_link)}</link>',
        f'  <atom:link href="{_safe(self_feed)}" rel="self" type="application/rss+xml" />',
        f'  <lastBuildDate>{_safe(last_build)}</lastBuildDate>',
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


def _load_digest(day):
    path = BASE / day.isoformat() / 'consolidated_recommendations.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if not data.get('completed') or not data.get('results') or len(data.get('all_results', [])) != data.get('total_reviewed'):
        raise RuntimeError('补发推荐尚未完整完成，停止发布')
    return data


def _digest_intro(digest, day, site_link):
    return (f'<p><strong>补发范围：{_safe(digest["start_date"])} 至 {_safe(digest["end_date"])}；'
            f'全文评审 {digest["total_reviewed"]} 篇，模型 {_safe(digest["model"])}。</strong></p>'
            + _paragraphs_html(digest['overview'])
            + '<p>评审范围：每篇最多使用 PDF 提取文本的前 50,000 字符；推荐基于逐篇评审、分组终评和跨组筛选。</p>'
            + f'<p><a href="{_safe(site_link)}days/{day.isoformat()}-all.html">查看全部 {digest["total_reviewed"]} 篇全文评审</a></p>')


def generate_site(days: int, out_dir: Path, site_link: str, title: str, desc: str) -> None:
    today = _today()
    day_records: List[Tuple[dt.date, List[Dict[str, Any]]]] = []
    digests = {}
    for i in range(days):
        day = today - dt.timedelta(days=i)
        digest = _load_digest(day)
        if digest:
            digests[day] = digest
    for i in range(days):
        day = today - dt.timedelta(days=i)
        digest = digests.get(day)
        if digest:
            day_records.append((day, digest['results']))
            continue
        if any(item['start_date'] <= day.isoformat() <= item['end_date'] for item in digests.values()):
            continue  # A consolidated recommendation already covers this source day.
        summary_path = BASE / day.isoformat() / 'reviews' / 'summary.json'
        if not summary_path.exists():
            continue
        screening = _load_screening(BASE / day.isoformat())
        if screening:
            with summary_path.open(encoding='utf-8') as stream:
                summary = json.load(stream)
            if summary.get('results') != screening or summary.get('total') != len(screening):
                continue
            day_records.append((day, screening))
    day_records.sort(key=lambda x: x[0], reverse=True)

    if not day_records:
        raise RuntimeError('最近窗口内没有可发布的评审结果；保留现有 RSS，停止空内容发布')

    out_dir.mkdir(parents=True, exist_ok=True)
    days_dir = out_dir / 'days'
    days_dir.mkdir(parents=True, exist_ok=True)

    for day, screening in day_records:
        (days_dir / f'{day.isoformat()}.html').write_text(_render_day_page(day, screening), encoding='utf-8')
        digest = _load_digest(day)
        if digest:
            full = _render_day_page(day, digest['all_results'], full_archive=True)
            (days_dir / f'{day.isoformat()}-all.html').write_text(full, encoding='utf-8')

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
