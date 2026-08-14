#!/usr/bin/env python3
"""国勢調査メッシュから半径500m/1km/2km圏の人口を計算するユーティリティ

日本の標準地域メッシュ(JIS X 0410)のコードは緯度経度から決定的に計算できる。
このモジュールは、メッシュコード→人口 の辞書(tools/census/mesh500_pop.csv 等から構築)を使い、
任意の地点(lat,lng)を中心とした半径R圏の合計人口を、メッシュ中心が円内にあるメッシュの
面積按分なしの単純合計(近似)で返す。500mメッシュは1辺約500mなので、500m/1km/2km圏の
比較には十分な精度。DataLensの商圏人口(令和2年国勢調査から算出)と同じ出典・粒度。

500mメッシュ(4次メッシュ/2分の1地域メッシュ)コードの構成:
  1次(約80km) 4桁 + 2次(約10km) 2桁 + 3次(約1km) 2桁 + 4次(500m) 1桁 = 9桁
"""
import csv, math, os, bisect

R_EARTH = 6371.0

def latlng_to_mesh500(lat, lng):
    """緯度経度 → 500mメッシュコード(9桁の文字列)"""
    # 1次メッシュ
    p = int(lat * 60 // 40)          # 緯度×60 ÷40分
    a = (lat * 60) % 40
    u = int(lng - 100)               # 経度-100度
    f = lng - 100 - u
    # 2次メッシュ
    q = int(a // 5)
    b = a % 5
    v = int((f * 60) // 7.5)
    g = f * 60 - v * 7.5
    # 3次メッシュ
    r = int(b * 60 // 30)
    c = (b * 60) % 30
    w = int(g * 60 // 45)
    h = g * 60 - w * 45
    # 4次(500m)メッシュ: 3次を南北・東西2分割 → 1..4
    s = 1 if c < 15 else 3
    if h >= 22.5:
        s += 1
    return f"{p:02d}{u:02d}{q}{v}{r}{w}{s}"

def mesh500_center(code):
    """500mメッシュコード → メッシュ中心の(lat,lng)"""
    p = int(code[0:2]); u = int(code[2:4])
    q = int(code[4]); v = int(code[5])
    r = int(code[6]); w = int(code[7])
    s = int(code[8])
    lat = p * 40 / 60 + q * 5 / 60 + r * 30 / 3600
    lng = 100 + u + v * 7.5 / 60 + w * 45 / 3600
    # 4次分割の中心オフセット(3次セル=30秒緯度×45秒経度、その1/4セルの中心)
    south = (s in (1, 2)); west = (s in (1, 3))
    lat += (7.5 if south else 22.5) / 3600          # 南半分は下(+7.5秒)、北半分は上(+22.5秒)
    lng += (11.25 if west else 33.75) / 3600         # 西半分は左、東半分は右
    return lat, lng

def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2 * R_EARTH * math.asin(math.sqrt(h))

class MeshPop:
    """メッシュ人口テーブル。CSVの列: KEY_CODE, total(総人口), age20_69(就業年齢) 等。

    age列が無ければ total に全国平均の就業年齢比率を掛けて近似する。
    """
    def __init__(self, csv_path, age_ratio_fallback=0.60):
        self.pts = []   # (lat, lng, total, age)
        self.age_ratio = age_ratio_fallback
        with open(csv_path, encoding='utf-8') as f:
            rd = csv.DictReader(f)
            cols = rd.fieldnames
            key_col = next((c for c in cols if c.upper() in ('KEY_CODE', 'MESH', 'MESHCODE', 'MESH_CODE')), cols[0])
            tot_col = next((c for c in cols if c in ('total', 'T001101001', 'population', '人口') or c.upper() == 'TOTAL'), None)
            # 20-69歳の各5歳階級列を合算(あれば)
            age_cols = [c for c in cols if any(f'{lo}_' in c or f'{lo}-' in c for lo in range(20, 70, 5))]
            for row in rd:
                code = str(row[key_col]).strip()
                if len(code) < 9:
                    continue
                try:
                    lat, lng = mesh500_center(code[:9])
                    total = float(row.get(tot_col, 0) or 0) if tot_col else 0
                    if age_cols:
                        age = sum(float(row.get(c, 0) or 0) for c in age_cols)
                    else:
                        age = total * self.age_ratio
                    self.pts.append((lat, lng, total, age))
                except Exception:
                    continue
        self.pts.sort()
        self.lats = [p[0] for p in self.pts]

    # 500mメッシュの半辺(緯度方向 15秒≒0.231km、経度方向 22.5秒≒緯度により変動)
    _HALF_LAT_KM = 15 / 3600 * 111.0

    def circle(self, lat, lng, radius_km):
        """(lat,lng)中心・半径radius_km圏の (総人口, 就業年齢人口) を面積按分で返す。

        各メッシュを 4×4 の小区画に分け、円内に入る小区画の割合で人口を按分する。
        500m圏(メッシュ数が少ない)でも境界の取りこぼし・拾いすぎを抑える。
        """
        cl = math.cos(math.radians(lat))
        half_lng_km = 22.5 / 3600 * 111.0 * cl
        margin = radius_km + self._HALF_LAT_KM * 1.5
        dlat = margin / 111.0
        i0 = bisect.bisect_left(self.lats, lat - dlat)
        i1 = bisect.bisect_right(self.lats, lat + dlat)
        r2 = radius_km * radius_km
        tot = age = 0.0
        offs = [-0.375, -0.125, 0.125, 0.375]   # 4×4分割の各小区画中心(半辺比)
        for la, lo, t, ag in self.pts[i0:i1]:
            dyc = (la - lat) * 111.0
            dxc = (lo - lng) * 111.0 * cl
            # 粗い早期棄却
            if abs(dyc) - self._HALF_LAT_KM > radius_km and abs(dxc) - half_lng_km > radius_km:
                continue
            inside = 0
            for oy in offs:
                dy = dyc + oy * 2 * self._HALF_LAT_KM
                for ox in offs:
                    dx = dxc + ox * 2 * half_lng_km
                    if dx * dx + dy * dy <= r2:
                        inside += 1
            if inside:
                frac = inside / 16.0
                tot += t * frac; age += ag * frac
        return round(tot), round(age)

    def trade_area(self, lat, lng):
        """500m/1km/2km の (総人口, 就業年齢人口) をまとめて返す"""
        return {r: self.circle(lat, lng, km)
                for r, km in [('m500', 0.5), ('m1000', 1.0), ('m2000', 2.0)]}


if __name__ == '__main__':
    # 自己テスト: メッシュコード↔中心の往復
    for lat, lng in [(35.7049, 139.5808), (34.6937, 135.5023), (43.0554, 141.3540)]:
        code = latlng_to_mesh500(lat, lng)
        clat, clng = mesh500_center(code)
        d = haversine((lat, lng), (clat, clng))
        print(f"({lat},{lng}) → mesh {code} → center({clat:.4f},{clng:.4f}) 距離{d*1000:.0f}m {'OK' if d<0.4 else 'NG'}")
