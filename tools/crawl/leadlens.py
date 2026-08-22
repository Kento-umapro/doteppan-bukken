#!/usr/bin/env python3
"""LeadLens(DataLens店舗開発)巡回: 社内メール由来の物件リードをAPIから取得して候補JSONを作る。

APIは緯度経度・可能業種(allowedIndustries)まで構造化済みなので、ジオコーディング不要で
重飲食可否も判定できる(どてっぱんは重飲食必須)。国勢調査商圏(500m/1km/2km)だけ付与する。

認証: 環境変数 LEADLENS_TOKEN に Cognito アクセストークン(Bearer)を渡す。
  (トークンは約1時間で失効。公開リポジトリには絶対書かない。ルーチンの非公開プロンプトから渡す)
  トークンが無い場合は LEADLENS_CACHE(既定: scratchpadのleads.json)を読む。

出力: tools/crawl/candidates_geo.json 形式(ll・pop500・m1000・m2000・m2000_total 付き)
使い方: LEADLENS_TOKEN=<token> python3 tools/crawl/leadlens.py
"""
import os, sys, json, subprocess, re, unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'census'))
from mesh import MeshPop  # noqa: E402

API = 'https://leadlens-api.nowcast-app.com/api/v1/propertyLeads?perPage=5000'
CA = '/root/.ccr/ca-bundle.crt'
CACHE = os.environ.get('LEADLENS_CACHE',
                       '/tmp/claude-0/-home-user-keiba-yosou/dc00dfb4-4d67-5b50-a343-f888e5d25a33/scratchpad/leads.json')

PREF = {'01': '北海道', '02': '青森県', '03': '岩手県', '04': '宮城県', '05': '秋田県', '06': '山形県',
        '07': '福島県', '08': '茨城県', '09': '栃木県', '10': '群馬県', '11': '埼玉県', '12': '千葉県',
        '13': '東京都', '14': '神奈川県', '15': '新潟県', '16': '富山県', '17': '石川県', '18': '福井県',
        '19': '山梨県', '20': '長野県', '21': '岐阜県', '22': '静岡県', '23': '愛知県', '24': '三重県',
        '25': '滋賀県', '26': '京都府', '27': '大阪府', '28': '兵庫県', '29': '奈良県', '30': '和歌山県',
        '31': '鳥取県', '32': '島根県', '33': '岡山県', '34': '広島県', '35': '山口県', '36': '徳島県',
        '37': '香川県', '38': '愛媛県', '39': '高知県', '40': '福岡県', '41': '佐賀県', '42': '長崎県',
        '43': '熊本県', '44': '大分県', '45': '宮崎県', '46': '鹿児島県', '47': '沖縄県'}


def fetch_leads():
    tok = os.environ.get('LEADLENS_TOKEN', '').strip()
    if tok:
        out = subprocess.run(['curl', '-sS', '-m', '60', '--cacert', CA,
                              '-H', 'Authorization: Bearer ' + tok, API],
                             capture_output=True, text=True).stdout
        d = json.loads(out)
        return d['propertyLeads']
    return json.load(open(CACHE))['propertyLeads']


def _addr_core(addr):
    """住所を『町名＋丁目＋番地先頭』の正規化キーに畳む(都道府県は除去)。既存店照合用。"""
    a = unicodedata.normalize('NFKC', addr or '')
    a = re.sub(r'^.{2,3}[都道府県]', '', a)           # 都道府県を落とす(リード側は無い場合もある)
    a = re.sub(r'\s', '', a)
    a = a.replace('丁目', '-').replace('番地', '-').replace('番', '-').replace('号', '')
    a = re.sub(r'-+', '-', a)
    m = re.match(r'(\D+-?\d+-?\d*)', a)              # 町名＋数字2グループ程度まで
    return (m.group(1) if m else a[:14]).rstrip('-')


def existing_store_cores():
    """判定エンジンのBASELINE(既存どてっぱん12店)の住所コア集合を返す。"""
    try:
        s = open(os.path.join(ROOT, 'tools/scoreing/index.html'), encoding='utf-8').read()
        return {_addr_core(a) for a in re.findall(r'address:"([^"]+)"', s)}
    except Exception:
        return set()


def floor_code(fmin):
    if fmin is None:
        return 'f1'
    if fmin < 0:
        return 'b1'
    return {1: 'f1', 2: 'f2'}.get(fmin, 'f3')


def main():
    mp = MeshPop(os.path.join(ROOT, 'tools', 'census', 'mesh500_pop.csv'))
    leads = fetch_leads()
    own = existing_store_cores()   # 既存どてっぱん店の住所コア(除外用)

    # 既存data.jsonのleadlens propertyLeadIdで重複排除
    d = json.load(open(os.path.join(ROOT, 'data.json')))
    seen = set()
    for tier in ['prefs', 'premium']:
        for v in d[tier].values():
            for x in v['items']:
                for _, u in (x.get('u') or []):
                    if 'leadlens:' in u:
                        seen.add(u.split('leadlens:')[1])

    out = []
    for L in leads:
        u = L['propertyUnit']
        ai = u.get('allowedIndustries') or []
        if '重飲食' not in ai:          # どてっぱんは重飲食必須
            continue
        pid = L.get('propertyLeadId')
        if pid in seen:
            continue
        loc = u.get('location') or {}
        lat, lng = loc.get('latitude'), loc.get('longitude')
        area = u.get('areaSpace') or 0
        rent = (u.get('rentPrice') or 0) + (u.get('maintenanceFee') or 0)  # 家賃=賃料+管理費(込み)
        if not (lat and lng) or not (20 <= area <= 40) or rent <= 0:
            continue
        tp = rent / area
        if not (6000 <= tp <= 40000):
            continue
        pref = PREF.get(str(loc.get('prefecture')), '')
        if not pref:
            continue
        addr = loc.get('address') or ''
        core = _addr_core(addr)
        if core and any(core == o or core.startswith(o) or o.startswith(core) for o in own):
            continue                         # 既存どてっぱん店と同一立地は除外
        if not addr.startswith(pref):
            addr = pref + addr
        ta = mp.trade_area(lat, lng)
        pop500 = ta['m500'][1]
        if pop500 < ta['m1000'][1] * 0.12:
            pop500 = (pop500 + ta['m1000'][1] * 0.24) / 2
        out.append({
            'id': 'leadlens-' + str(pid), 'source': 'leadlens', 'cd': L.get('displayCode') or '',
            'url': 'https://umapro.leadlens.nowcast-app.com/property#leadlens:' + str(pid),
            'pref': pref, 'title': (u.get('propertyUnitName') or '')[:60], 'addr': addr[:60],
            'rent': int(rent), 'area': round(area, 1), 'tsubo_price': round(tp),
            'station': (loc.get('nearestStation') or '')[:20], 'floor': '', 'fc': floor_code(u.get('floorMin')),
            'll': [round(lat, 5), round(lng, 5)], 'pop500': round(pop500),
            'm1000': ta['m1000'][1], 'm2000': ta['m2000'][1], 'm2000_total': round(ta['m2000'][0]),
            'bucket': ('premium' if (tp > 20000 and rent <= 1000000) else 'prefs'),
            'priority': True, 'juusyoku': True,
        })

    json.dump(out, open(os.path.join(BASE, 'candidates_geo.json'), 'w'), ensure_ascii=False)
    print(f'LeadLens 重飲食可・基準内候補 {len(out)}件 → candidates_geo.json')


if __name__ == '__main__':
    main()
