#!/usr/bin/env python3
"""hungry/data.json 生成スクリプト

親リポジトリの data.json(どてっぱん巡回データ・全物件)から、
stores.json の各店舗から半径5km圏内にある物件を抽出して hungry/data.json を作る。
毎朝の巡回で親 data.json を更新したあとに実行すること:
    python3 hungry/build.py
"""
import json, math, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
RADIUS_KM = 5.0

def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))

stores = json.load(open(os.path.join(BASE, 'stores.json')))
src = json.load(open(os.path.join(BASE, '..', 'data.json')))

items, seen = [], set()
for tier in ['prefs', 'premium']:
    for pref, v in src.get(tier, {}).items():
        for x in v['items']:
            if not x.get('ll'):
                continue
            near, dist = [], {}
            for s in stores:
                if not s.get('ll'):
                    continue
                d = hav(x['ll'], s['ll'])
                if d <= RADIUS_KM:
                    near.append(s['id'])
                    dist[s['id']] = round(d, 2)
            if not near:
                continue
            key = (x.get('u') or [['', x['a'] + x.get('n', '')]])[0][1]
            if key in seen:   # 標準/上級の重複掲載を除去
                continue
            seen.add(key)
            y = dict(x)
            y.pop('sc', None); y.pop('rk', None); y.pop('pr', None)  # 本サイトは5km条件のみ
            y['near'] = near
            y['dist'] = dist
            items.append(y)

out = {
    'generated': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M'),
    'stores': stores,
    'items': items,
}
json.dump(out, open(os.path.join(BASE, 'data.json'), 'w'),
          ensure_ascii=False, separators=(',', ':'))
print(f"stores={len(stores)} items={len(items)}")
for s in stores:
    n = sum(1 for x in items if s['id'] in x['near'])
    if n:
        print(f"  {s['name']}: {n}件")
