#!/usr/bin/env python3
"""Publish selected options dates; monthly rules and Cboe currently listed weekly series."""
import argparse
import calendar
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo('America/New_York')
HOLIDAYS = 'https://raw.githubusercontent.com/rickeylau/market-holidays/main/holidays.json'
HOLIDAY_OFFICIAL = 'https://www.cboe.com/about/hours/us-options/'
WEEKLY = 'https://www.cboe.com/available_weeklys/'
SPX = 'https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications'
SPXO = 'https://www.cboe.com/insights/posts/cboe-introduces-am-settled-weekly-options-on-the-s-p-500-index/'
VIX = 'https://www.cboe.com/tradable-products/vix/vix-options/specifications'
OIC = 'https://www.optionseducation.org/referencelibrary/expiration-calendar'
HFILE = ROOT/'holidays_snapshot.json'
WFILE = ROOT/'listed_weeklys.json'
OUT = ROOT/'options-expiration.ics'
KEYS = {'spx_am','monthly_opex','month_end','vix_weekly','spxo'}


def get(url):
    req = Request(url, headers={'User-Agent':'Mozilla/5.0 (OptionsExpirationCalendar)', 'Accept':'*/*'})
    with urlopen(req, timeout=40) as r:
        data = r.read(4_000_001)
    if len(data)>4_000_000:
        raise ValueError('Download too large')
    return data


def validate_holidays(payload, current_year):
    if payload.get('source') != HOLIDAY_OFFICIAL:
        raise ValueError('Unexpected holiday source')
    datetime.strptime(payload['stamp'], '%Y%m%dT%H%M%SZ')
    years = {}
    for e in payload['events']:
        d = date.fromisoformat(e['date'])
        if d.weekday() >= 5 or not e['holiday'] or e['close'] not in (None, '13:00'):
            raise ValueError(f'Invalid holiday: {e}')
        y = years.setdefault(d.year, {})
        if d in y: raise ValueError(f'Duplicate date {d}')
        y[d] = e['close']
    if current_year not in years: raise ValueError('Current year holiday data missing')
    for y, exceptions in years.items():
        if not 9 <= sum(x is None for x in exceptions.values()) <= 20:
            raise ValueError(f'Incomplete holiday schedule {y}')
    return years


def parse_weeklys(html):
    soup = BeautifulSoup(html, 'html.parser')
    result = {}
    for table in soup.find_all('table'):
        rows = {}
        for tr in table.find_all('tr'):
            cells = tr.find_all(['td','th'], recursive=False)
            if not cells: continue
            key = ' '.join(cells[0].stripped_strings).strip().upper()
            if key not in {'VIX','SPXO'}: continue
            # The listing table dates use US mm/dd/yy, not product overview rows.
            dates = set()
            for cell in cells[1:]:
                for match in re.findall(r'\b\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\b', cell.get_text(' ',strip=True)):
                    dates.add(datetime.strptime(match, '%m/%d/%Y' if len(match.split('/')[-1])==4 else '%m/%d/%y').date().isoformat())
            if key in rows: raise ValueError(f'Duplicate listing row {key}')
            rows[key] = sorted(dates)
        if set(rows)=={'VIX','SPXO'} and all(rows.values()):
            if result: raise ValueError('Multiple listing tables')
            result = rows
    if not result or not all(result.values()):
        raise ValueError('No usable VIX/SPXO listing dates; refusing to replace snapshot')
    return result


def fetch_weeklys_browser():
    """Wait for the official dynamic expiry table, then parse its rendered HTML."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale='en-US')
            response = page.goto(WEEKLY, wait_until='domcontentloaded', timeout=60_000)
            if response is not None and not response.ok:
                raise RuntimeError(f'Cboe returned HTTP {response.status}')
            # Require both rows and actual dates in the same table. The static
            # product overview also contains the symbols, but has no dates.
            page.wait_for_function(r"""() => {
                const date = /\b\d{1,2}\/\d{1,2}\/(?:\d{4}|\d{2})\b/;
                return [...document.querySelectorAll('table')].some(table => {
                    const rows = [...table.rows];
                    return ['VIX', 'SPXO'].every(symbol => rows.some(row => {
                        const cells = [...row.cells];
                        return cells.length > 1 &&
                            cells[0].textContent.trim().toUpperCase() === symbol &&
                            cells.slice(1).some(c => date.test(c.textContent));
                    }));
                });
            }""", timeout=90_000)
            return parse_weeklys(page.content())
        finally:
            browser.close()


def fetch_weeklys():
    """Try static HTML first; fall back to a real JS-enabled browser."""
    today = datetime.now(ET).date().isoformat()
    def check(listed):
        for symbol in ('VIX', 'SPXO'):
            if not any(d >= today for d in listed[symbol]):
                raise ValueError(f'No current/future {symbol} dates in Cboe listing')
        validate_weeklys({'stamp': '20000101T000000Z', **listed})
        return listed
    try:
        listed = check(parse_weeklys(get(WEEKLY)))
        print('Cboe weekly dates: static HTML')
        return listed
    except (ValueError, OSError) as exc:
        print(f'Static listing unavailable: {exc}; using Chromium', flush=True)
    listed = check(fetch_weeklys_browser())
    print('Cboe weekly dates: rendered Chromium page')
    return listed


def validate_weeklys(payload):
    datetime.strptime(payload['stamp'], '%Y%m%dT%H%M%SZ')
    for k in ('VIX','SPXO'):
        vals = payload[k]
        if len(set(vals))!=len(vals): raise ValueError(f'Duplicate {k} dates')
        for s in vals:
            if date.fromisoformat(s).weekday() >= 5: raise ValueError(f'Weekend {k}: {s}')


def trading(d, years):
    if d.year not in years: raise ValueError(f'No holiday data for {d.year}')
    return d.weekday()<5 and years[d.year].get(d,'16:00') is not None


def previous(d, years):
    while not trading(d, years): d -= timedelta(days=1)
    return d


def third_friday(y,m):
    d=date(y,m,1)
    return d+timedelta(days=(4-d.weekday())%7+14)


def utc(d,t):
    return datetime.combine(d,time.fromisoformat(t),ET).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def escape(s):
    return s.replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;')


def fold(s):
    out=[]; part=''
    for ch in s:
        if len((part+ch).encode('utf-8'))>75: out.append(part);part=' '+ch
        else: part+=ch
    return '\r\n'.join(out+[part])


def render(holidays, weekly, cfg, current_year):
    years=validate_holidays(holidays,current_year)
    validate_weeklys(weekly)
    if set(cfg)!=KEYS or any(type(v) is not bool for v in cfg.values()): raise ValueError('Invalid config')
    stamp=max(holidays['stamp'],weekly['stamp'])
    events={}
    def add(key,d,t,title,desc,url):
        if (key,d) in events: raise ValueError('Duplicate event')
        if t is None:
            timing=[f'DTSTART;VALUE=DATE:{d:%Y%m%d}',f'DTEND;VALUE=DATE:{d+timedelta(days=1):%Y%m%d}']
        else:
            start=datetime.combine(d,time.fromisoformat(t),ET)
            end=start+timedelta(minutes=5)
            timing=[f'DTSTART:{utc(d,t)}',f'DTEND:{end.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}']
        events[key,d]=['BEGIN:VEVENT',f'UID:{key}-{d.isoformat()}@options-expiration',f'DTSTAMP:{stamp}',*timing,f'SUMMARY:{escape(title)}',f'DESCRIPTION:{escape(desc)}',f'URL:{url}','TRANSP:TRANSPARENT','END:VEVENT']
    for y in sorted(years):
        for m in range(1,13):
            expiry=previous(third_friday(y,m),years)
            last=previous(expiry-timedelta(days=1),years)
            close=years[y].get(expiry,'16:00')
            if cfg['spx_am']:
                add('spx-am-last',last,None,'SPX AM Monthly - Last Trading Day','Normally 17:00 ET; check special-session hours and broker cutoff. Standard monthly AM settlement is on the next trading day. Rule-based date; verify exchange notices.',SPX)
                add('spx-am',expiry,'09:30','SPX AM Monthly Settlement','Opening SET calculation based on component opening prices; 09:30 ET marks the regular open, not guaranteed publication. Rule-based date.',SPX)
            if cfg['monthly_opex']:
                title='Quarterly OPEX / Triple Witching' if m%3==0 else 'Monthly OPEX - SPXW / SPY'
                add('opex',expiry,close,title,'SPXW PM expiry cutoff and underlying regular-session close; SPY option trading and exercise cutoffs differ. Quarterly date combines monthly OPEX and quarterly witching. Rule-based date; verify listed series.',OIC)
            if cfg['month_end']:
                last_month=previous(date(y,m,calendar.monthrange(y,m)[1]),years)
                end=years[y].get(last_month,'16:00')
                title='SPXW Quarter-End Expiration (EOQ)' if m%3==0 else 'SPXW Month-End Expiration (EOM)'
                add('eom',last_month,end,title,'PM-settled SPXW expiration at the regular close; rule-based date. Quarter-end replaces month-end to avoid duplicate reminders.',SPX)
    for k,enabled in [('VIX',cfg['vix_weekly']),('SPXO',cfg['spxo'])]:
        if not enabled: continue
        for s in weekly[k]:
            d=date.fromisoformat(s)
            if d.year in years and not trading(d,years): raise ValueError(f'Listed {k} on closed day {d}')
            title='VIX Weekly Options Settlement' if k=='VIX' else 'SPXO AM Weekly Settlement'
            desc=('Official Cboe Available Weeklys listing. SOQ is determined from opening prices; 09:30 ET is the opening reference, not publication time. Monthly VIX settlement is excluded.' if k=='VIX' else 'Official Cboe listed SPXO date; AM settlement using opening SET, not SPXW PM settlement. 09:30 ET is the opening reference; verify last trade and contract specifications.')
            add(k.lower(),d,'09:30',title,desc,WEEKLY)
    if not events: raise ValueError('Empty calendar')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Options Expiration//EN','CALSCALE:GREGORIAN','X-WR-CALNAME:Options Expiration','X-WR-TIMEZONE:America/New_York','X-WR-CALDESC:SPX AM and PM expirations plus officially listed VIX and SPXO weekly series. Verify exchange notices.']
    for key in sorted(events,key=lambda k:(k[1],k[0])): lines.extend(events[key])
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(fold(x) for x in lines)+'\r\n').encode(),len(events)


def write(path,data):
    if not path.exists() or path.read_bytes()!=data:
        tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_bytes(data);tmp.replace(path)


def main():
    p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');args=p.parse_args()
    today=datetime.now(ET).date()
    h=json.loads(HFILE.read_text()); w=json.loads(WFILE.read_text()); cfg=json.loads((ROOT/'config.json').read_text())
    if not args.offline:
        fresh=json.loads(get(HOLIDAYS).decode('utf-8'))
        old_years=validate_holidays(h,max(date.fromisoformat(e['date']).year for e in h['events']))
        new_years=validate_holidays(fresh,today.year)
        if not set(old_years).issubset(new_years): raise ValueError('Holiday coverage shrank')
        h=fresh
        listed=fetch_weeklys()
        new={k:sorted(set(s for s in w[k] if s<=today.isoformat())|set(listed[k])) for k in ('VIX','SPXO')}
        if any(new[k]!=w[k] for k in new): w={'stamp':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),**new}
    data,count=render(h,w,cfg,today.year)
    for path,payload in ((HFILE,h),(WFILE,w)):
        write(path,(json.dumps(payload,indent=2,ensure_ascii=False)+'\n').encode())
    write(OUT,data)
    print(f'{count} events; listed weeklies: VIX={len(w["VIX"])}, SPXO={len(w["SPXO"])}')

if __name__=='__main__': main()
