#!/usr/bin/env python3
"""score-cli.js の判定結果を data.json に反映する

使い方: python3 tools/scoreing/apply-results.py tools/scoreing/pending.result.json

- 偏差値50以上: sc / rk / pr を付与し、ll(Googleジオコーディング座標)も更新
- 偏差値50未満: 掲載から削除。ただしスカイスクレイパー店舗5km圏内(HUNGREE対象)の
  物件は hungree/extra.json に退避して HUNGREE には掲載を維持する(ops(8)の運用)
- 東京都補正(-2.0pt)は score-cli.js 側で適用済み
- 最後に hungree/build.py を実行して HUNGREE のデータも再生成する
"""
import json, math, os, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, '..', '..')

def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))

results = {r['key']: r for r in json.load(open(sys.argv[1])) if r.get('key') and not r.get('error')}
d = json.loads(open(os.path.join(ROOT, 'data.json')).read())
stores = json.load(open(os.path.join(ROOT, 'hungree', 'stores.json')))
extra_path = os.path.join(ROOT, 'hungree', 'extra.json')
extra = json.load(open(extra_path)) if os.path.exists(extra_path) else []

listed = removed = archived = 0
for tier in ['prefs', 'premium']:
    for pref, v in d[tier].items():
        keep = []
        for x in v['items']:
            key = (x.get('u') or [['', '']])[0][1] or (x['a'] + x.get('n', ''))
            r = results.get(key)
            if x.get('sc') or not r:
                keep.append(x)
                continue
            if r.get('ll'):
                x['ll'] = r['ll']
            if r['sc'] >= 50:
                x['sc'] = r['sc']
                x['rk'] = r['rank']
                lo, hi = r.get('profitRange') or [None, None]
                if lo is not None:
                    x['pr'] = f'+{lo}万〜+{hi}万'
                keep.append(x)
                listed += 1
            else:
                removed += 1
                if x.get('ll') and any(s.get('ll') and hav(x['ll'], s['ll']) <= 5.0 for s in stores):
                    extra.append(x)
                    archived += 1
        v['items'] = keep

json.dump(extra, open(extra_path, 'w'), ensure_ascii=False, separators=(',', ':'))
open(os.path.join(ROOT, 'data.json'), 'w').write(
    json.dumps(d, ensure_ascii=False, separators=(',', ':')))
print(f'掲載 {listed}件 / 50未満削除 {removed}件(うちHUNGREE退避 {archived}件)')
subprocess.run([sys.executable, os.path.join(ROOT, 'hungree', 'build.py')], check=True)
