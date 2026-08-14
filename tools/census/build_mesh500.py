import csv, glob, io, zipfile, os

# Column map for T001101 (2020 census 500m mesh) - selected cumulative brackets
# T001101001 人口総数, 002 男, 003 女
# 004 0-14総数, 010 15-64総数, 007 15+総数, 013 18+総数, 019 20+総数, 022 65+総数, 025 75+総数
COLS = {
    'T001101001':'total','T001101002':'male','T001101003':'female',
    'T001101004':'age_0_14','T001101010':'age_15_64','T001101007':'age_15plus',
    'T001101013':'age_18plus','T001101016':'age_20plus','T001101019':'age_65plus',
    'T001101022':'age_75plus',
}
def num(v):
    v=(v or '').strip()
    if v in ('','*','-','X','x'): return 0
    try: return int(v)
    except: 
        try: return int(float(v))
        except: return 0

rows={}
meshcodes=set()
for z in sorted(glob.glob('T001101_*.zip')):
    mc=z.split('_')[1].split('.')[0]
    with zipfile.ZipFile(z) as zf:
        name=[n for n in zf.namelist() if n.endswith('.txt')][0]
        data=zf.read(name).decode('cp932')
    r=csv.reader(io.StringIO(data))
    header=next(r)
    idx={h:i for i,h in enumerate(header)}
    next(r)  # label row
    cnt=0
    for row in r:
        if not row or not row[0].strip(): continue
        kc=row[0].strip()
        rec={'KEY_CODE':kc}
        for col,out in COLS.items():
            rec[out]=num(row[idx[col]]) if col in idx else 0
        # working-age proxy: 20-64 = 20+ minus 65+
        rec['age20_69']=max(0, rec['age_20plus']-rec['age_65plus'])
        rows[kc]=rec
        cnt+=1
    meshcodes.add(mc)
    print(f'{z}: {cnt} rows')

out_cols=['KEY_CODE','total','male','female','age_0_14','age_15_64',
          'age_15plus','age_18plus','age_20plus','age_65plus','age_75plus','age20_69']
with open('mesh500_pop.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=out_cols)
    w.writeheader()
    for kc in sorted(rows):
        w.writerow(rows[kc])

tot=sum(r['total'] for r in rows.values())
wrk=sum(r['age20_69'] for r in rows.values())
print(f'\nTotal meshes(500m): {len(rows)}')
print(f'Sum pop_total: {tot:,}')
print(f'Sum working_20_64: {wrk:,}')
print(f'1st-mesh codes: {sorted(meshcodes)}')
