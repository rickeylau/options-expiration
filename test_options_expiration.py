import json
import unittest
from datetime import date
from options_expiration import ROOT, parse_weeklys, render, validate_holidays, previous, third_friday, utc

class TestExpiration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h=json.loads((ROOT/'holidays_snapshot.json').read_text())
        cls.w=json.loads((ROOT/'listed_weeklys.json').read_text())
        cls.cfg=json.loads((ROOT/'config.json').read_text())
    def test_holiday_monthly(self):
        y=validate_holidays(self.h,2026)
        for year in (2026,2027):
            actual=previous(third_friday(year,6),y)
            self.assertEqual(actual,date(year,6,18 if year==2026 else 17))
    def test_timezone(self):
        self.assertEqual(utc(date(2026,11,20),'09:30'),'20261120T143000Z')
        self.assertEqual(utc(date(2027,7,16),'16:00'),'20270716T200000Z')
    def test_weekly_parser(self):
        html='<table><tr><td>VIX</td><td>12/09/26</td><td>12/23/26</td></tr><tr><td>SPXO</td><td>11/18/26</td><td>12/16/26</td></tr></table>'
        self.assertEqual(parse_weeklys(html)['SPXO'],['2026-11-18','2026-12-16'])
        with self.assertRaises(ValueError): parse_weeklys('<html>error</html>')
    def test_calendar(self):
        b,n=render(self.h,self.w,self.cfg,2026)
        self.assertEqual(n,4*24+len(self.w['VIX'])+len(self.w['SPXO']))
        self.assertEqual(b.count(b'BEGIN:VEVENT'),b.count(b'END:VEVENT'))
        self.assertTrue(b.endswith(b'END:VCALENDAR\r\n'))
        self.assertTrue(all(len(line)<=75 for line in b.split(b'\r\n')))
        u=[x for x in b.split(b'\r\n') if x.startswith(b'UID:')];self.assertEqual(len(u),len(set(u)))
        self.assertIn(b'UID:opex-2027-06-17@options-expiration',b)
        self.assertIn(b'UID:spx-am-last-2027-06-16@options-expiration',b)
        self.assertNotIn(b'UID:vix-2026-11-18',b)
    def test_disabled(self):
        cfg={**self.cfg,'vix_weekly':False,'spxo':False}
        b,n=render(self.h,self.w,cfg,2026)
        self.assertNotIn(b'VIX Weekly Options Settlement',b)
        self.assertNotIn(b'SPXO AM Weekly Settlement',b)
        self.assertEqual(n,96)

if __name__=='__main__': unittest.main()
