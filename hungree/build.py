#!/usr/bin/env python3
"""hungry/data.json 生成スクリプト

親リポジトリの data.json(どてっぱん巡回データ・全物件)から、
stores.json の各店舗から半径5km圏内にある物件を抽出して hungry/data.json を作る。
毎朝の巡回で親 data.json を更新したあとに実行すること:
    python3 hungry/build.py
"""
import json, math, os, re, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
RADIUS_KM = 5.0

# 家賃負担ランク(坪単価・共益費込み目安ベース)
# ココイチ型の採算では家賃比率が重くなるため、高坪単価(特に東京)は低評価になる
def rent_rank(x):
    tkv = None
    m = re.search(r'([\d.]+)', str(x.get('tk') or ''))
    if m:
        tkv = float(m.group(1))
    else:
        mr = re.search(r'([\d.]+)', str(x.get('r') or ''))
        mt = re.search(r'([\d.]+)', str(x.get('t') or ''))
        if mr and mt and float(mt.group(1)) > 0:
            tkv = float(mr.group(1)) / float(mt.group(1))
    if tkv is None:
        return None
    if tkv <= 1.2: return 'A'
    if tkv <= 1.8: return 'B'
    if tkv <= 2.5: return 'C'
    return 'D'

def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))

stores = json.load(open(os.path.join(BASE, 'stores.json')))
src = json.load(open(os.path.join(BASE, '..', 'data.json')))

# extra.json: どてっぱん側の基準(偏差値50未満等)で親data.jsonから削除されたが、
# 本サイトの条件(5km圏内)は満たす物件の退避先。巡回セッションは削除時にここへ移すこと。
extra_path = os.path.join(BASE, 'extra.json')
extra = json.load(open(extra_path)) if os.path.exists(extra_path) else []

# found.json: HUNGREE専用巡回の収集先。crawl-areas.json の各店舗5km圏エリアで見つけた
# 飲食可の貸店舗を、どてっぱんの基準(坪数・坪単価)に関係なくここへ追加する。
# 形式は親data.jsonのitemsと同じ(n/a/ll/t/r/rs/tk/s/f/c/d/u/ad)。ll必須。
found_path = os.path.join(BASE, 'found.json')
found = json.load(open(found_path)) if os.path.exists(found_path) else []

def all_items():
    for tier in ['prefs', 'premium']:
        for pref, v in src.get(tier, {}).items():
            for x in v['items']:
                yield x
    for x in extra:
        yield x
    for x in found:
        yield x

items, seen = [], set()
for x in all_items():
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
    if key in seen:   # 標準/上級/退避分の重複を除去
        continue
    seen.add(key)
    y = dict(x)
    y.pop('sc', None); y.pop('rk', None); y.pop('pr', None)  # 偏差値は本サイト対象外
    y['near'] = near
    y['dist'] = dist
    y['rb'] = rent_rank(x)  # 家賃負担ランク A/B/C/D
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
