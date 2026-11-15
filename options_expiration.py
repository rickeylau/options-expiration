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
