#!/usr/bin/env node
/* candidates_geo.json を判定して data.json に追加する。
 *
 * - 競合300m を Google Places から取得（GOOGLE_API_KEY 必須。日次上限に当たった分は
 *   競合中立=暫定 pv:1 として掲載）
 * - 偏差値(sc)は index.html の計算エンジンで算出（東京都は -2.0pt）
 * - v4予測倍率(pm)= 国勢調査商圏の売上予測 ÷ 家賃（訪日エリア×1.7・競合で微調整）
 * - 掲載下限(2026-08-20 月商＋2km商圏基準・標準/上級 共通):
 *     20坪以上 / 出店偏差値50以上 / 予測月商300万以上 / 商圏500m就業人口1000以上 /
 *     2km総人口3万以上 / 2km就業年齢人口3万以上(労働者数の代理)
 *   （「月商300万を狙える都市商圏」に限定。予測月商は商圏人口から算出するため商圏が直接効く。
 *    真の労働者数=経済センサス従業者数は未取得のため、就業年齢人口で代理している）
 * - 各物件に ad=今日 を付与。掲載30日超は別途 expire で処理。
 *
 * 使い方: GOOGLE_API_KEY=<key> node tools/crawl/judge_add.js <YYYY-MM-DD>
 */
const fs = require('fs'), path = require('path');
const BASE = __dirname, ROOT = path.join(BASE, '..', '..');
const KEY = process.env.GOOGLE_API_KEY || '';
const TODAY = process.argv[2] || new Date().toISOString().slice(0, 10);

const src = fs.readFileSync(path.join(ROOT, 'tools/scoreing/index.html'), 'utf8');
function ex(a, b) { const i = src.indexOf(a), j = src.indexOf(b, i); return src.slice(i, j); }
eval(ex('const BASELINE = [', '// ============ 既存店ランキング計算 & 描画 ============').replace(/const |let /g, 'var '));
eval(ex('// ============ 業態分類 (Google primaryType ベース) ============', 'async function fetchCompetitors').replace(/const /g, 'var '));
BASELINE.forEach(s => { s.profit = Math.round(s.revenue * s.ebitda); });
var scored = BASELINE.map(s => ({ ...s, scores: computeScores(s) }));
CALIBRATED_W = calibrateWeights(scored);

const A = 85060, B = 7.118, INB = 1.70;
const INBOUND_KW = ['祇園', '木屋町', '河原町', '先斗町', '四条', '東山', '新地', '心斎橋', '難波', '道頓堀', '宗右衛門'];
const TYPES = ['restaurant', 'bar', 'cafe', 'fast_food_restaurant', 'japanese_restaurant', 'sushi_restaurant', 'ramen_restaurant', 'italian_restaurant', 'chinese_restaurant', 'korean_restaurant', 'thai_restaurant', 'vietnamese_restaurant', 'mexican_restaurant', 'french_restaurant', 'indian_restaurant', 'barbecue_restaurant', 'steak_house', 'pizza_restaurant', 'hamburger_restaurant', 'brunch_restaurant', 'breakfast_restaurant', 'pub', 'wine_bar', 'meal_takeaway'];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const rank = sc => sc >= 65 ? 'S' : sc >= 58 ? 'A' : sc >= 52 ? 'B' : sc >= 45 ? 'C' : 'D';

async function nearby(ll) {
  if (!KEY) return null;
  for (let a = 0; a < 3; a++) {
    try {
      const r = await fetch('https://places.googleapis.com/v1/places:searchNearby', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Goog-Api-Key': KEY, 'X-Goog-FieldMask': 'places.displayName,places.primaryType,places.primaryTypeDisplayName,places.types,places.userRatingCount' },
        body: JSON.stringify({ includedTypes: TYPES, maxResultCount: 20, languageCode: 'ja', regionCode: 'JP', locationRestriction: { circle: { center: { latitude: ll[0], longitude: ll[1] }, radius: 300 } } })
      });
      if (r.status === 429) return null; // 日次上限 → 暫定扱い
      const j = await r.json();
      return (j.places || []).map(p => ({ name: p.displayName?.text || '', primaryType: p.primaryType, primaryTypeDisplayName: p.primaryTypeDisplayName?.text || '', types: p.types || [], ratingCount: p.userRatingCount || 0 }));
    } catch (e) { await sleep(2000); }
  }
  return null;
}

(async () => {
  const cand = JSON.parse(fs.readFileSync(path.join(BASE, 'candidates_geo.json'), 'utf8'));
  const d = JSON.parse(fs.readFileSync(path.join(ROOT, 'data.json'), 'utf8'));
  const exist = new Set();
  for (const tier of ['prefs', 'premium'])
    for (const pref in d[tier]) for (const x of d[tier][pref].items)
      for (const u of (x.u || [])) exist.add(u[1]);

  let added = 0;
  for (const r of cand) {
    const url = r.url || `https://www.temposmart.jp/estates/${r.id}`;
    if (exist.has(url)) continue;
    const pl = await nearby(r.ll);
    const hasC = pl !== null;
    const c = { direct: 0, synergy: 0, neutral: 0, directW: 0, synergyW: 0, neutralW: 0 };
    (pl || []).forEach(p => { const cat = classifyEstablishment(p), w = computeWeight(p.ratingCount); if (cat === 'direct') { c.direct++; c.directW += w; } else if (cat === 'synergy') { c.synergy++; c.synergyW += w; } else if (cat === 'neutral') { c.neutral++; c.neutralW += w; } });
    ['directW', 'synergyW', 'neutralW'].forEach(k => c[k] = Math.round(c[k] * 10) / 10);
    const inp = { tsubo: r.area, seats: Math.round(r.area * 1.5), floor: ({ f1: 1, f2: 2, b1: -1, f3: 2 })[r.fc] || 2, rent: r.rent, pop500: r.pop500, target2049: r.pop500, search: 7000, hire: 'C', compDirect: c.direct, compSynergy: c.synergy, compNeutral: c.neutral, compDirectWeighted: c.directW, compSynergyWeighted: c.synergyW, compNeutralWeighted: c.neutralW };
    let total = computeTotal(computeScores(inp), 'どてっぱん');
    if (/^東京都/.test(r.addr)) total -= 2.0;
    const sc = Math.round(total * 10) / 10;
    if (sc < 50) continue;                 // 掲載下限: 出店偏差値50以上(既存店平均以上)
    let pred = A + B * r.pop500;
    if ((r.pref === '京都府' || r.pref === '大阪府') && INBOUND_KW.some(k => r.addr.includes(k) || r.title.includes(k))) pred *= INB;
    let pr = pred * r.area;
    const adj = Math.max(0.6, Math.min(1.2, 1 + Math.min(c.synergyW * 0.01, 0.15) - c.directW * 0.03 - c.neutralW * 0.005));
    pr *= adj;
    const pm = Math.round(pr / r.rent * 10) / 10;
    const prv = Math.round(pr / 1e4);      // 予測月商(万円)=予測坪月商(商圏人口ベース)×坪数
    // 掲載下限(2026-08-20 月商＋2km商圏基準): 20坪以上・予測月商300万以上・
    // 商圏500m就業人口1000以上・2km総人口3万以上・2km就業年齢人口3万以上(労働者数の代理)。
    if (r.area < 20 || prv < 300 || (r.pop500 || 0) < 1000) continue;
    if ((r.m2000_total || 0) < 30000 || (r.m2000 || 0) < 30000) continue;
    const tier = r.bucket, pref = r.pref;
    if (!d[tier][pref]) d[tier][pref] = { note: `${pref}／テンポスマート巡回`, items: [] };
    const rentman = r.rent / 10000;
    const fn = [];
    const item = { ll: r.ll, sc, rk: rank(sc), pm, prv, s: r.fc, n: r.title, a: r.addr, st: r.station, t: `${r.area}坪`, r: (rentman === Math.floor(rentman) ? `${rentman}万円` : `${rentman.toFixed(1)}万円`), rs: '', tk: `約${(r.tsubo_price / 10000).toFixed(2)}万円`, d: '要問い合わせ', c: 'から探す', f: 'ok', u: [[r.source==='tshop'?'テナントショップ':'テンポスマート', url]], ad: TODAY };
    if (!hasC) { item.pv = 1; fn.push('競合データ取得待ち・暫定'); }
    if (r.source !== 'tshop') fn.push('番地はログイン後開示');
    item.fn = fn.join('／');
    d[tier][pref].items.push(item);
    exist.add(url); added++;
    if (hasC) await sleep(300);
  }
  d.generated = TODAY + 'T10:00';
  fs.writeFileSync(path.join(ROOT, 'data.json'), JSON.stringify(d));  // 既存と同じ詰め形式(UTF-8)
  console.log(`追加 ${added}件`);
})();
