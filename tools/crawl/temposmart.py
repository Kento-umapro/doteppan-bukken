#!/usr/bin/env python3
"""テンポスマート巡回: 一覧ページから店舗物件を収集して候補JSONを出力する

temposmart.jp は一覧ページ(/estates/pref/<code>?page=N)がサーバーレンダリングで
取得でき、カードに名称・賃料・坪数・階数・最寄駅・町丁目住所が入っている
(番地はログイン後表示だが町丁目まででジオコーディング可能)。
飲食店ドットコム・テンポダスはSPA/bot対策で不可のため、当面temposmartのみ。

対応都道府県(temposmartの掲載範囲・JISコード): 首都圏+関西のみ。
  東京13 神奈川14 埼玉11 千葉12 京都26 大阪27 兵庫28
  ※重点エリアの愛知23・群馬10・滋賀25は temposmart 非対応(別ソースが必要)。

出力: tools/crawl/candidates.json (既存data.jsonとURL重複排除済み・基準内)
使い方: python3 tools/crawl/temposmart.py
"""
import subprocess, re, json, time, os

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, '..', '..')
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CA = "/root/.ccr/ca-bundle.crt"

# temposmartが掲載を持つ都道府県。重点エリア(大阪京都埼玉千葉)を優先。
PREFS = {'大阪府': 27, '京都府': 26, '埼玉県': 11, '千葉県': 12,
         '東京都': 13, '神奈川県': 14, '兵庫県': 28}
# 重点7府県(緩和基準17坪〜・偏差値48〜)
PRIORITY = {'大阪府', '京都府', '滋賀県', '愛知県', '群馬県', '埼玉県', '千葉県'}
MAX_PAGES = 16  # 1ページ50件。大阪は約736件あるため深掘りして全在庫を拾う

def fetch(url):
    args = ['curl', '-sS', '--max-time', '25', '-A', UA]
    if os.path.exists(CA):
        args += ['--cacert', CA]
    return subprocess.run(args + [url], capture_output=True, text=True).stdout

def _txt(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s or '')).strip()

def parse(html):
    rows = []
    for c in re.split(r'<div class="estateItem"[ >]', html)[1:]:
        g = lambda p: (re.search(p, c, re.S) or [None, ''])[1]
        idv = g(r'estateId--value">([0-9]+)')
        if not idv:
            continue
        rent = g(r'estatePrice--value">([\d.,]+)').replace(',', '')
        area = g(r'estateArea">.*?([\d.]+)\s*坪')
        rows.append(dict(
            id=idv,
            title=_txt(g(r'estateTitle">\s*<a[^>]*>(.*?)</a>'))[:60],
            rent=int(rent) if rent else 0,
            area=float(area) if area else 0.0,
            floor=_txt(g(r'estateFloor">(.*?)</div>'))[:12],
            station=_txt(g(r'stationInfo__name">(.*?)</div>'))[:30],
            addr=_txt(g(r'estateAddress">(.*?)</div>')).split(' 枝番')[0][:40],
        ))
    return rows

def floor_code(f):
    if 'B' in f or '地下' in f:
        return 'b1'
    if re.search(r'(^|[^0-9])1階', f):
        return 'f1'
    if '2階' in f:
        return 'f2'
    return 'f3'

def main():
    # 既存data.jsonのtemposmart IDで重複排除
    d = json.load(open(os.path.join(ROOT, 'data.json')))
    existing = set()
    for tier in ['prefs', 'premium']:
        for v in d[tier].values():
            for x in v['items']:
                for _, u in (x.get('u') or []):
                    m = re.search(r'temposmart\.jp/estates/(\d+)', u)
                    if m:
                        existing.add(m.group(1))

    raw = {}
    for pref, code in PREFS.items():
        seen = set()
        for pg in range(1, MAX_PAGES + 1):
            rows = parse(fetch(f"https://www.temposmart.jp/estates/pref/{code}?page={pg}"))
            new = [r for r in rows if r['id'] not in seen]
            if not new:
                break
            for r in new:
                r['pref'] = pref
                seen.add(r['id'])
                raw[r['id']] = r
            time.sleep(0.5)
        print(f"{pref}: {len(seen)}件")

    cand = []
    for r in raw.values():
        if r['id'] in existing:
            continue
        if '飲食不' in r['title']:
            continue
        if r['rent'] <= 0 or r['area'] <= 0:
            continue
        lo = 20   # 掲載下限20坪(2026-08-20)。全エリア20〜40坪で収集
        if not (lo <= r['area'] <= 40):
            continue
        tp = r['rent'] / r['area']
        if not (6000 <= tp <= 40000):
            continue
        r['tsubo_price'] = round(tp)
        r['bucket'] = 'premium' if (tp > 20000 and r['rent'] <= 1000000) else 'prefs'
        r['fc'] = floor_code(r['floor'])
        r['priority'] = r['pref'] in PRIORITY
        cand.append(r)

    out = os.path.join(BASE, 'candidates.json')
    json.dump(cand, open(out, 'w'), ensure_ascii=False)
    print(f"新規候補 {len(cand)}件 → {out}")

if __name__ == '__main__':
    main()
