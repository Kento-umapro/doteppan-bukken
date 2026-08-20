#!/usr/bin/env python3
"""滋賀(テナントショップ)の既掲載物件の実所在階を取り直し、1階路面のみに絞る一度限りの整理。
重飲食は排気・ガスの都合で1階が現実的なため、2階/3階/地下は held.json へ退避する。
結果は data.json / tools/crawl/held.json に反映。"""
import json, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tshop import fetch, floor_code_from_detail, _shozaikai  # noqa

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
d = json.load(open(os.path.join(ROOT, 'data.json')))
items = d['prefs'].get('滋賀県', {}).get('items', [])
held = json.load(open(os.path.join(ROOT, 'tools/crawl/held.json')))

keep, moved, dist = [], 0, {}
for x in items:
    url = x['u'][0][1]
    fc = floor_code_from_detail(fetch(url))
    dist[fc] = dist.get(fc, 0) + 1
    x['s'] = fc
    if fc == 'f1':
        note = x.get('fn', '')
        if '重飲食' not in note:
            x['fn'] = (note + '／重飲食は要確認(前業態不明)').strip('／')
        keep.append(x)
    else:
        held.append(x)
        moved += 1
    time.sleep(0.1)

d['prefs']['滋賀県']['items'] = keep
json.dump(held, open(os.path.join(ROOT, 'tools/crawl/held.json'), 'w'), ensure_ascii=False)
json.dump(d, open(os.path.join(ROOT, 'data.json'), 'w'), ensure_ascii=False)
lab = {'f1': '1階', 'f2': '2階', 'f3': '3階以上', 'b1': '地下'}
print('所在階分布:', {lab.get(k, k): v for k, v in dist.items()})
print(f'滋賀 1階路面のみ {len(keep)}件 / 非1階を退避 {moved}件')
