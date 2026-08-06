#!/usr/bin/env python3
"""判定待ち物件の抽出 → score-cli.js 用の入力JSON(pending.json)を生成する

使い方: python3 tools/scoreing/make-pending.py
出力: tools/scoreing/pending.json

pop500 / target2049 / search / hire は物件情報からは機械抽出できないため
null / 既定値で出力する。判定セッションは実行前に商圏の概算値で埋めること
(500m総人口 pop500 は必須。target2049 省略時はツールと同じく pop500×44% で推定される)。
"""
import json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, '..', '..')

def man(s):
    m = re.search(r'([\d.]+)\s*万', str(s or '').replace(',', ''))
    return float(m.group(1)) if m else 0.0

def num(s):
    m = re.search(r'([\d.]+)', str(s or '').replace(',', ''))
    return float(m.group(1)) if m else None

d = json.load(open(os.path.join(ROOT, 'data.json')))
out = []
for tier in ['prefs', 'premium']:
    for pref, v in d[tier].items():
        for x in v['items']:
            if x.get('sc'):
                continue
            tsubo = num(x.get('t'))
            rent = (man(x.get('r')) + man(x.get('rs'))) * 10000  # 共益費込み・円
            if not tsubo or not rent:
                continue
            key = (x.get('u') or [['', '']])[0][1] or (x['a'] + x.get('n', ''))
            out.append({
                'key': key,
                'tier': tier,
                'pref': pref,
                'name': x.get('n', ''),
                'address': x['a'],
                'tsubo': tsubo,
                'floor': {'f1': 1, 'f2': 2, 'b1': -1, 'f3': 2}.get(x.get('s'), 2),
                'rent': round(rent),
                'pop500': None,      # ← 判定前に商圏推定で埋める(必須)
                'target2049': None,  # ← 任意(空なら pop500×44% で推定)
                'search': None,      # ← 月間検索需要の概算(空なら0扱いで不利になるため埋める)
                'hire': 'C',         # ← 採用難易度 A〜E
            })
path = os.path.join(BASE, 'pending.json')
json.dump(out, open(path, 'w'), ensure_ascii=False, indent=1)
print(f'判定待ち {len(out)}件 → {path}')
