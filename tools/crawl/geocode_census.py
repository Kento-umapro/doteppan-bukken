#!/usr/bin/env python3
"""candidates.json をジオコーディング(Geolonia町丁目)し、国勢調査商圏人口を付与する。

出力: tools/crawl/candidates_geo.json（ll・m500/m1000/m2000 を追加、座標不明は除外）
前提: tools/census/mesh500_pop.csv（同梱）と Geolonia latest.csv（無ければ取得）。
使い方: python3 tools/crawl/geocode_census.py
"""
import json, csv, re, os, sys, subprocess, unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'census'))
from mesh import MeshPop  # noqa: E402

LATEST = os.path.join(BASE, 'latest.csv')
if not os.path.exists(LATEST):
    subprocess.run(['curl', '-sS', '--max-time', '300', '--cacert', '/root/.ccr/ca-bundle.crt',
                    '-o', LATEST,
                    'https://raw.githubusercontent.com/geolonia/japanese-addresses/master/data/latest.csv'])

towns = {}
with open(LATEST, encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if r['緯度']:
            towns[(r['都道府県名'], r['市区町村名'], r['大字町丁目名'])] = (float(r['緯度']), float(r['経度']))

KAN = dict(zip('0123456789', '〇一二三四五六七八九'))
def _k(n):
    n = int(n)
    if n >= 100: return None
    if n < 10: return KAN[str(n)]
    if n < 20: return '十' + (KAN[str(n % 10)] if n % 10 else '')
    return KAN[str(n // 10)] + '十' + (KAN[str(n % 10)] if n % 10 else '')
def _z(s): return unicodedata.normalize('NFKC', s)

def geocode(pref, addr):
    a = _z(addr)
    rest = a[len(pref):] if a.startswith(pref) else a
    cities = [c for (p, c, t) in towns if p == pref and rest.startswith(c)]
    if not cities:
        return None
    city = max(cities, key=len)
    tail = rest[len(city):]
    dd = {t: v for (p, c, t), v in towns.items() if p == pref and c == city}
    tries = []
    m = re.match(r'(.*?)(\d{1,2})', tail)
    if m and m.group(2):
        tries.append(m.group(1) + (_k(m.group(2)) or '') + '丁目')
    plain = re.sub(r'\d.*', '', tail).rstrip('丁目')
    tries += [re.sub(r'\d+', lambda x: _k(x.group()) or x.group(), tail), plain, plain + '一丁目']
    for t in tries:
        if t in dd:
            return [round(dd[t][0], 5), round(dd[t][1], 5)]
    pre = [v for t, v in dd.items() if plain and t.startswith(plain)]
    if pre:
        return [round(sum(x[0] for x in pre) / len(pre), 5), round(sum(x[1] for x in pre) / len(pre), 5)]
    return None

def main():
    mp = MeshPop(os.path.join(ROOT, 'tools', 'census', 'mesh500_pop.csv'))
    cand = json.load(open(os.path.join(BASE, 'candidates.json')))
    out = []
    for r in cand:
        ll = geocode(r['pref'], r['addr'])
        if not ll:
            continue
        ta = mp.trade_area(*ll)
        pop500 = ta['m500'][1]
        if pop500 < ta['m1000'][1] * 0.12:
            pop500 = (pop500 + ta['m1000'][1] * 0.24) / 2
        r['ll'] = ll
        r['pop500'] = round(pop500)
        r['m1000'] = ta['m1000'][1]
        r['m2000'] = ta['m2000'][1]              # 2km就業年齢人口(労働者数の代理)
        r['m2000_total'] = round(ta['m2000'][0])  # 2km総人口
        out.append(r)
    json.dump(out, open(os.path.join(BASE, 'candidates_geo.json'), 'w'), ensure_ascii=False)
    print(f"ジオコーディング成功 {len(out)}/{len(cand)}件")

if __name__ == '__main__':
    main()
