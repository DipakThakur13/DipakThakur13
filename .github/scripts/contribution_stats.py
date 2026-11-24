#!/usr/bin/env python3
"""Render an animated contribution stats card for the profile README.

Reads the public contribution calendar through the GitHub GraphQL API and
writes an SVG with total contributions, contribution days, current and
longest streak, plus contributions per month for the last 12 months.

Usage:
    GITHUB_TOKEN=... python3 contribution_stats.py <github-user> <output.svg>
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

API = 'https://api.github.com/graphql'
DAY = dt.timedelta(days=1)

SANS = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Ubuntu, Roboto, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'Cascadia Code', Consolas, 'Liberation Mono', Menlo, monospace"

ACCENT = '#38bdf8'      # current month + tile icons
PAST = '#0284c7'        # de-emphasised months
SURFACE = '#0b1220'


# --------------------------------------------------------------------------- data
def gql(query, variables, token):
    body = json.dumps({'query': query, 'variables': variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        'Authorization': f'bearer {token}',
        'Content-Type': 'application/json',
        'User-Agent': 'profile-contribution-stats',
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get('errors'):
        raise RuntimeError(json.dumps(payload['errors']))
    return payload['data']


def fetch_calendar(user, token, today):
    meta = gql(
        'query($login:String!){user(login:$login){createdAt contributionsCollection{contributionYears}}}',
        {'login': user}, token)['user']
    years = set(meta['contributionsCollection']['contributionYears']) | {today.year}
    query = ('query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){'
             'contributionsCollection(from:$from,to:$to){contributionCalendar{'
             'weeks{contributionDays{date contributionCount}}}}}}')
    days = {}
    for year in sorted(years):
        data = gql(query, {'login': user, 'from': f'{year}-01-01T00:00:00Z',
                           'to': f'{year}-12-31T23:59:59Z'}, token)
        weeks = data['user']['contributionsCollection']['contributionCalendar']['weeks']
        for week in weeks:
            for d in week['contributionDays']:
                date = dt.date.fromisoformat(d['date'])
                if date.year == year and date <= today:
                    days[date] = d['contributionCount']
    created = dt.date.fromisoformat(meta['createdAt'][:10])
    return created, days


def compute(days, created, today):
    active = sorted(d for d, c in days.items() if c > 0)
    first = active[0] if active else created

    # current streak: today may still be empty without breaking the streak
    cur_end = today if days.get(today, 0) > 0 else today - DAY
    d, cur = cur_end, 0
    while days.get(d, 0) > 0:
        cur += 1
        d -= DAY
    cur_start = d + DAY

    best, best_range, run, run_start = 0, None, 0, None
    d = first
    while d <= today:
        if days.get(d, 0) > 0:
            if run == 0:
                run_start = d
            run += 1
            if run > best:
                best, best_range = run, (run_start, d)
        else:
            run = 0
        d += DAY

    best_day = max(days.items(), key=lambda kv: (kv[1], kv[0]), default=(today, 0))

    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    per_month = {ym: 0 for ym in months}
    for date, count in days.items():
        if (date.year, date.month) in per_month:
            per_month[(date.year, date.month)] += count

    span = (today - first).days + 1
    return {
        'total': sum(days.values()),
        'active_days': len(active),
        'span_days': span,
        'first': first,
        'current': cur,
        'current_range': (cur_start, cur_end) if cur else None,
        'longest': best,
        'longest_range': best_range,
        'best_day': best_day,
        'this_year': sum(c for date, c in days.items() if date.year == today.year),
        'months': [(ym, per_month[ym]) for ym in months],
    }


# --------------------------------------------------------------------------- formatting
def fmt_num(n):
    if n >= 10_000:
        return f'{n / 1000:.1f}K'.replace('.0K', 'K')
    return f'{n:,}'


def fmt_date(d, today, force_year=False):
    s = f'{d.day} {d:%b}'
    return f'{s} {d.year}' if force_year or d.year != today.year else s


def fmt_range(rng, today):
    a, b = rng
    if a == b:
        return fmt_date(a, today)
    if b == today:
        return f'{fmt_date(a, today)} – today'
    return f'{fmt_date(a, today)} – {fmt_date(b, today)}'


def nice_step(x):
    """Smallest 1/2/5 x 10^k step that is >= x (minimum 1)."""
    if x <= 1:
        return 1
    mag = 10 ** (len(str(int(x))) - 1)
    for f in (1, 2, 5, 10):
        if f * mag >= x:
            return f * mag
    return 10 * mag


# --------------------------------------------------------------------------- icons
def icon(kind, cx, cy):
    a = ACCENT
    if kind == 'commit':
        return (f'<path d="M{cx - 12} {cy}H{cx - 5.5}M{cx + 5.5} {cy}H{cx + 12}" stroke="{a}" stroke-width="2.2" stroke-linecap="round"/>'
                f'<circle class="ping" cx="{cx}" cy="{cy}" r="5" fill="none" stroke="{a}" stroke-width="2.2"/>')
    if kind == 'calendar':
        return (f'<rect x="{cx - 9}" y="{cy - 8}" width="18" height="17" rx="3.5" fill="none" stroke="{a}" stroke-width="2"/>'
                f'<path d="M{cx - 9} {cy - 3}H{cx + 9}M{cx - 4} {cy - 11}V{cy - 6}M{cx + 4} {cy - 11}V{cy - 6}" stroke="{a}" stroke-width="2" stroke-linecap="round"/>'
                f'<rect class="tick" x="{cx - 5}" y="{cy + 1}" width="4" height="4" rx="1" fill="{a}"/>')
    if kind == 'flame':
        return (f'<path class="flame" d="M{cx} {cy - 11}C{cx + 7} {cy - 5} {cx + 9} {cy} {cx + 8} {cy + 4}'
                f'C{cx + 7} {cy + 10} {cx + 2} {cy + 11} {cx} {cy + 11}C{cx - 5} {cy + 11} {cx - 8} {cy + 7} {cx - 8} {cy + 3}'
                f'C{cx - 8} {cy - 1} {cx - 5} {cy - 3} {cx - 4} {cy - 7}C{cx - 2} {cy - 4} {cx - 1} {cy - 3} {cx + 1} {cy - 2}'
                f'C{cx + 2} {cy - 5} {cx + 1} {cy - 8} {cx} {cy - 11}Z" fill="{a}" fill-opacity=".25" stroke="{a}" stroke-width="2" stroke-linejoin="round"/>')
    if kind == 'trophy':
        return (f'<path d="M{cx - 7} {cy - 10}H{cx + 7}V{cy - 3}A7 7 0 0 1 {cx - 7} {cy - 3}Z" fill="{a}" fill-opacity=".25" stroke="{a}" stroke-width="2" stroke-linejoin="round"/>'
                f'<path d="M{cx - 7} {cy - 7}H{cx - 11}V{cy - 5}A4 4 0 0 0 {cx - 6.5} {cy - 1}M{cx + 7} {cy - 7}H{cx + 11}V{cy - 5}A4 4 0 0 1 {cx + 6.5} {cy - 1}'
                f'M{cx} {cy + 4}V{cy + 8}M{cx - 5} {cy + 10}H{cx + 5}" fill="none" stroke="{a}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    raise ValueError(kind)


# --------------------------------------------------------------------------- render
def render(user, s, today):
    W, H, P = 1200, 470, 40
    tile_w, gap, ty, th = 265, 20, 112, 142

    cur_sub = fmt_range(s['current_range'], today) if s['current'] else 'No active streak'
    long_sub = fmt_range(s['longest_range'], today) if s['longest'] else 'No streak yet'
    pct = round(100 * s['active_days'] / s['span_days']) if s['span_days'] else 0
    tiles = [
        ('commit', 'Total contributions', fmt_num(s['total']), '', f'since {fmt_date(s["first"], today, True)}'),
        ('calendar', 'Contribution days', fmt_num(s['active_days']), 'days', f'{pct}% of {s["span_days"]:,} days'),
        ('flame', 'Current streak', fmt_num(s['current']), 'days', cur_sub),
        ('trophy', 'Longest streak', fmt_num(s['longest']), 'days', long_sub),
    ]

    tile_els, clips = [], []
    for i, (kind, label, value, unit, sub) in enumerate(tiles):
        x = P + i * (tile_w + gap)
        delay = 0.15 + i * 0.12
        unit_el = f'<tspan font-size="19" font-weight="500" fill="#94a3b8" dx="8">{unit}</tspan>' if unit else ''
        clips.append(f'<clipPath id="v{i}"><rect x="{x}" y="{ty + 60}" width="{tile_w}" height="54"/></clipPath>')
        tile_els.append(f'''
<g>
  <rect x="{x}" y="{ty}" width="{tile_w}" height="{th}" rx="16" fill="#0f1a30" stroke="#1e293b"/>
  <rect class="bar-in" x="{x + 18}" y="{ty}" width="{tile_w - 36}" height="2" rx="1" fill="{ACCENT}" style="animation-delay:{delay:.2f}s"/>
  <circle cx="{x + 40}" cy="{ty + 38}" r="20" fill="{ACCENT}" fill-opacity=".1" stroke="{ACCENT}" stroke-opacity=".35"/>
  {icon(kind, x + 40, ty + 38)}
  <text class="sans" x="{x + 72}" y="{ty + 44}" font-size="17" fill="#94a3b8">{escape(label)}</text>
  <g clip-path="url(#v{i})"><text class="sans val" x="{x + 24}" y="{ty + 104}" font-size="44" font-weight="600" fill="#f8fafc" style="animation-delay:{delay + 0.1:.2f}s">{escape(value)}{unit_el}</text></g>
  <text class="sans" x="{x + 24}" y="{ty + 128}" font-size="14.5" fill="#64748b">{escape(sub)}</text>
</g>''')

    # ---- monthly columns
    px0, px1, top, base = 84, W - P, 330, 424
    months = s['months']
    vmax = max(v for _, v in months)
    step = nice_step(vmax / 3)
    n_ticks = max(2, -(-vmax // step))
    ymax = step * n_ticks
    slot = (px1 - px0) / len(months)
    bw = 24
    grid = []
    for k in range(n_ticks + 1):
        val = step * k
        y = base - (base - top) * val / ymax
        grid.append(f'<line x1="{px0}" y1="{y:.1f}" x2="{px1}" y2="{y:.1f}" stroke="#1e293b" stroke-width="1"/>'
                    f'<text class="mono tickl" x="{px0 - 12}" y="{y + 4:.1f}">{fmt_num(val)}</text>')
    best_idx = max(range(len(months)), key=lambda i: (months[i][1], i))
    cols, labels = [], []
    for i, ((yy, mm), v) in enumerate(months):
        cx = px0 + slot * (i + 0.5)
        x = cx - bw / 2
        current = i == len(months) - 1
        name = dt.date(yy, mm, 1).strftime('%b')
        labels.append(f'<text class="sans mlabel{" now" if current else ""}" x="{cx:.1f}" y="{base + 24}">{name}</text>')
        if v <= 0:
            continue
        h = max(2.0, (base - top) * v / ymax)
        r = min(4.0, h, bw / 2)
        yt = base - h
        d = (f'M{x:.1f} {base}V{yt + r:.1f}Q{x:.1f} {yt:.1f} {x + r:.1f} {yt:.1f}'
             f'H{x + bw - r:.1f}Q{x + bw:.1f} {yt:.1f} {x + bw:.1f} {yt + r:.1f}V{base}Z')
        delay = 0.5 + i * 0.06
        cols.append(f'<path class="col" d="{d}" fill="{ACCENT if current else PAST}" style="animation-delay:{delay:.2f}s"/>')
        if current or i == best_idx:
            cols.append(f'<text class="mono vlabel" x="{cx:.1f}" y="{yt - 9:.1f}" style="animation-delay:{delay + 0.6:.2f}s">{fmt_num(v)}</text>')

    bd_date, bd_count = s['best_day']
    best_txt = (f'Best day <tspan fill="#e2e8f0" font-weight="600">{fmt_num(bd_count)}</tspan> on {fmt_date(bd_date, today, True)}'
                if bd_count else 'Best day —')
    updated = fmt_date(today, today, True)

    desc = (f'{user} contribution stats, updated {updated}. Total contributions: {s["total"]:,} since {fmt_date(s["first"], today, True)}. '
            f'Contribution days: {s["active_days"]:,} ({pct}% of {s["span_days"]:,} days). '
            f'Current streak: {s["current"]} days ({cur_sub}). Longest streak: {s["longest"]} days ({long_sub}). '
            f'This year: {s["this_year"]:,}. Best day: {bd_count} on {fmt_date(bd_date, today, True)}. Contributions per month, last 12 months: '
            + ', '.join(f'{dt.date(y, m, 1):%b %Y} {v}' for (y, m), v in months) + '.')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">
<title id="title">Contribution stats for {escape(user)}</title>
<desc id="desc">{escape(desc)}</desc>
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0d1629"/><stop offset="1" stop-color="#060b18"/></linearGradient>
<linearGradient id="edge" x1="0" y1="0" x2="{W}" y2="0" gradientUnits="userSpaceOnUse">
<stop offset="0" stop-color="{ACCENT}"/><stop offset=".32" stop-color="#1e293b"/><stop offset=".68" stop-color="#1e293b"/><stop offset="1" stop-color="#818cf8"/>
<animateTransform attributeName="gradientTransform" type="rotate" from="0 {W / 2} {H / 2}" to="360 {W / 2} {H / 2}" dur="9s" repeatCount="indefinite"/>
</linearGradient>
<radialGradient id="glow" cx="90%" cy="0%" r="60%"><stop offset="0" stop-color="#2563eb" stop-opacity=".2"/><stop offset="1" stop-color="#2563eb" stop-opacity="0"/></radialGradient>
<clipPath id="frame"><rect width="{W}" height="{H}" rx="22"/></clipPath>
{''.join(clips)}
</defs>
<style>
.sans{{font-family:{SANS}}}
.mono{{font-family:{MONO}}}
.tickl{{font-size:12px;fill:#64748b;text-anchor:end;font-variant-numeric:tabular-nums}}
.mlabel{{font-size:14px;fill:#94a3b8;text-anchor:middle}}
.now{{fill:#f8fafc;font-weight:600}}
.vlabel{{font-size:13px;fill:#e2e8f0;text-anchor:middle;animation:fade .5s ease-out backwards}}
.val{{animation:rise .9s cubic-bezier(.2,.7,.2,1) backwards}}
.bar-in{{transform-box:fill-box;transform-origin:0 50%;animation:draw 1s cubic-bezier(.2,.7,.2,1) backwards}}
.col{{transform-box:fill-box;transform-origin:50% 100%;animation:grow .9s cubic-bezier(.2,.7,.2,1) backwards}}
.ping{{transform-box:fill-box;transform-origin:center;animation:ping 2.4s ease-in-out infinite}}
.flame{{transform-box:fill-box;transform-origin:50% 100%;animation:flicker 1.6s ease-in-out infinite}}
.tick{{animation:blink 2s steps(1) infinite}}
.live{{animation:blink 2s ease-in-out infinite}}
@keyframes rise{{from{{transform:translateY(40px);opacity:0}}}}
@keyframes draw{{from{{transform:scaleX(0)}}}}
@keyframes grow{{from{{transform:scaleY(0)}}}}
@keyframes fade{{from{{opacity:0}}}}
@keyframes ping{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.25)}}}}
@keyframes flicker{{0%,100%{{transform:scale(1) rotate(0deg)}}30%{{transform:scale(1.06,.95) rotate(-3deg)}}60%{{transform:scale(.96,1.05) rotate(2deg)}}}}
@keyframes blink{{50%{{opacity:.25}}}}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important}}}}
</style>
<g clip-path="url(#frame)">
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<rect width="{W}" height="{H}" fill="url(#glow)"/>
</g>
<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="21.5" fill="none" stroke="url(#edge)" stroke-width="1.5"/>

<text class="sans" x="{P}" y="62" font-size="26" font-weight="600" fill="#f8fafc">Contribution stats</text>
<text class="sans" x="{P}" y="89" font-size="15" fill="#94a3b8">@{escape(user)} · contributing since {fmt_date(s["first"], today, True)}</text>
<circle class="live" cx="{W - P - 6}" cy="57" r="4.5" fill="#22c55e"/>
<text class="mono" x="{W - P - 20}" y="62" font-size="13" fill="#64748b" text-anchor="end">Updated {updated}</text>

{''.join(tile_els)}

<text class="sans" x="{P}" y="300" font-size="17" font-weight="600" fill="#cbd5e1">Contributions per month <tspan font-weight="400" fill="#64748b">· last 12 months</tspan></text>
<text class="sans" x="{W - P}" y="300" font-size="15" fill="#94a3b8" text-anchor="end">This year <tspan fill="#e2e8f0" font-weight="600">{fmt_num(s["this_year"])}</tspan> · {best_txt}</text>
{''.join(grid)}
{''.join(cols)}
{''.join(labels)}
</svg>
'''


def main():
    if len(sys.argv) != 3:
        sys.exit('usage: contribution_stats.py <github-user> <output.svg>')
    user, out = sys.argv[1], sys.argv[2]
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        sys.exit('GITHUB_TOKEN is not set')
    today = dt.datetime.now(dt.timezone.utc).date()
    created, days = fetch_calendar(user, token, today)
    stats = compute(days, created, today)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(render(user, stats, today))
    print(f'wrote {out}: total={stats["total"]} days={stats["active_days"]} '
          f'current={stats["current"]} longest={stats["longest"]}')


if __name__ == '__main__':
    main()
