#!/usr/bin/env python3
"""テナントショップ(t-shop.co.jp)巡回: 滋賀県の貸店舗を収集して候補JSONに追加する。

t-shop.co.jp は滋賀特化でサーバーレンダリング(一覧・詳細とも取得可)。
一覧: /index.php?ac=2&c=12&pa=5&p=<page>  (pa=5=滋賀, 30件/ページ)
詳細: /detail/e-<id>/  (番地までの住所・階数・駅・賃料・坪数)

出力: tools/crawl/candidates.json に「店舗系・17〜40坪」を追記
      (temposmart.py が先に作っていれば追記、無ければ新規作成)
使い方: python3 tools/crawl/tshop.py
"""
import subprocess, re, json, time, os

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, '..', '..')
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CA = "/root/.ccr/ca-bundle.crt"
HOST = "https://www.t-shop.co.jp"
MAX_PAGES = 34  # 滋賀 約993件 ÷ 30

def fetch(url):
    args = ['curl', '-sS', '--max-time', '25', '-A', UA]
    if os.path.exists(CA):
        args += ['--cacert', CA]
    return subprocess.run(args + [url], capture_output=True, text=True).stdout

def _clean(s):
    return re.sub(r'\s+', '', re.sub(r'<[^>]+>', ' ', s or '')).strip()

def parse_list(html):
    rows = []
    for c in re.split(r'<table[^>]*class="result"', html)[1:]:
        m = re.search(r'/detail/e-(\d+)/', c)
        if not m:
            continue
        g = lambda cls: _clean((re.search(r'class="' + cls + r'[^"]*">(.*?)</div>', c, re.S) or [None, ''])[1])
        rows.append(dict(id=m.group(1), typ=g('esttype'), name=g('estatename'),
                         price=g('price'), tsubo=g('tsubo_val')))
    return rows

def floor_code_from_detail(html):
    m = re.search(r'(地下\s*\d+\s*階|B\s*\d\s*F|\d+\s*階|\d+\s*F)', html)
    if not m:
        return 'f1'
    f = m.group(1)
    if 'B' in f or '地下' in f:
        return 'b1'
    if re.search(r'(^|[^0-9])1\s*(階|F)', f):
        return 'f1'
    if re.search(r'2\s*(階|F)', f):
        return 'f2'
    return 'f3'

def parse_detail(html):
    addr = (re.search(r'(滋賀県[^\s<、,）)]{3,30})', html) or [None, ''])[1]
    station = (re.search(r'([^\s<>「」]{2,10}駅)', html) or [None, ''])[1]
    return addr[:40], station[:20], floor_code_from_detail(html)

def main():
    cand_path = os.path.join(BASE, 'candidates.json')
    cand = json.load(open(cand_path)) if os.path.exists(cand_path) else []
    # 既存data.jsonの t-shop ID で重複排除
    d = json.load(open(os.path.join(ROOT, 'data.json')))
    existing = set()
    for tier in ['prefs', 'premium']:
        for v in d[tier].values():
            for x in v['items']:
                for _, u in (x.get('u') or []):
                    m = re.search(r't-shop\.co\.jp/detail/e-(\d+)', u)
                    if m:
                        existing.add(m.group(1))

    picked = []
    for pg in range(1, MAX_PAGES + 1):
        rows = parse_list(fetch(f"{HOST}/index.php?ac=2&c=12&pa=5&p={pg}"))
        if not rows:
            break
        for r in rows:
            if '店舗' not in (r['typ'] or ''):
                continue  # 貸店舗系のみ(倉庫/工場/土地/事務所単独は除外)
            if r['id'] in existing:
                continue
            pm = re.search(r'([\d.]+)万', r['price'] or '')
            tm = re.search(r'([\d.]+)坪', r['tsubo'] or '')
            if not pm or not tm:
                continue
            rent = int(float(pm.group(1)) * 10000)
            area = float(tm.group(1))
            if not (17 <= area <= 40):
                continue
            tp = rent / area
            if not (6000 <= tp <= 40000):
                continue
            picked.append(dict(id=r['id'], name=r['name'], rent=rent, area=area, tsubo_price=round(tp)))
        time.sleep(0.4)

    added = 0
    for p in picked:
        html = fetch(f"{HOST}/detail/e-{p['id']}/")
        addr, station, fc = parse_detail(html)
        if not addr:
            continue
        cand.append(dict(
            id='tshop-' + p['id'], url=f"{HOST}/detail/e-{p['id']}/",
            source='tshop', pref='滋賀県', title=p['name'][:60], addr=addr,
            rent=p['rent'], area=p['area'], tsubo_price=p['tsubo_price'],
            station=station, floor='', fc=fc,
            bucket=('premium' if (p['tsubo_price'] > 20000 and p['rent'] <= 1000000) else 'prefs'),
            priority=True))
        added += 1
        time.sleep(0.3)

    json.dump(cand, open(cand_path, 'w'), ensure_ascii=False)
    print(f"テナントショップ滋賀: 店舗候補 {added}件を追加 → candidates.json (計{len(cand)})")

if __name__ == '__main__':
    main()
