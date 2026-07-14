#!/usr/bin/env node
/**
 * 無人スコア判定CLI - 物件スコア判定ツール(index.html)と同一ロジックで自動査定する
 *
 * 画面の「🌐 Googleで自動取得」→「スコア判定」と同じ処理を、ボタン操作なしで実行する。
 * 計算エンジン(BASELINE・重み較正・5軸偏差値)と業態分類は index.html から実行時に
 * そのまま抽出して使うため、ツール本体を更新すればこのCLIも自動で追従する。
 *
 * 使い方:
 *   DVS_URL=https://<ツールのURL> DVS_TOKEN=<ACCESS_TOKEN> node score-cli.js <入力JSON>
 *
 * 入力JSON: 物件の配列
 *   [{ "name":"物件名", "address":"住所", "tsubo":35.9, "rent":829000,
 *      "floor":1,            // 1=1階路面 / 2=2階以上 / -1=地下
 *      "pop500":11000,       // 500m総人口(概算可)
 *      "target2049":5300,    // 省略時は pop500×44% で推定(ツールと同じ)
 *      "seats":54,           // 省略時は 坪×1.5(ツールと同じ)
 *      "search":9000, "hire":"B" }]
 *
 * 出力: 各物件のスコア内訳を表示し、<入力JSON>.result.json に保存する。
 * 競合データはツールのサーバーAPI(/api/places/geocode, /api/places/nearby)経由で
 * Google Placesから取得する(半径100m・口コミ加重、画面と同一)。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const DVS_URL = (process.env.DVS_URL || '').replace(/\/+$/, '');
const DVS_TOKEN = process.env.DVS_TOKEN || '';
const inputPath = process.argv[2];

if (!DVS_URL || !inputPath) {
  console.error('使い方: DVS_URL=https://<ツールURL> DVS_TOKEN=<ACCESS_TOKEN> node score-cli.js <入力JSON>');
  process.exit(1);
}

// ---- index.html から計算エンジンと業態分類を抽出(改変せずそのまま実行) ----
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
function extract(startMarker, endMarker) {
  const s = html.indexOf(startMarker);
  const e = html.indexOf(endMarker, s);
  if (s < 0 || e < 0) throw new Error(`index.htmlから抽出失敗: ${startMarker}`);
  return html.slice(s, e);
}
const engineCode = extract('const BASELINE = [', '// ============ 既存店ランキング計算 & 描画 ============');
const classifyCode = extract('// ============ 業態分類 (Google primaryType ベース) ============', 'async function fetchCompetitors');

const sandbox = {};
vm.createContext(sandbox);
// const/let宣言はvmグローバルに載らないため、末尾で明示的にエクスポートする
const exportLine = '\n;this.BASELINE=BASELINE;this.computeScores=computeScores;this.computeTotal=computeTotal;'
  + 'this.calibrateWeights=calibrateWeights;this.deriveRank=deriveRank;'
  + 'this.classifyEstablishment=classifyEstablishment;this.computeWeight=computeWeight;'
  + 'this.setCalibratedW=(w)=>{CALIBRATED_W=w;};';
vm.runInContext(engineCode + '\n' + classifyCode + exportLine, sandbox);
const { BASELINE, computeScores, computeTotal, calibrateWeights, deriveRank, classifyEstablishment, computeWeight } = sandbox;

// 起動時較正(ツールの computeBaselineResults と同じ手順)
BASELINE.forEach(s => { s.profit = Math.round(s.revenue * s.ebitda); });
const scoredBaseline = BASELINE.map(s => ({ ...s, scores: computeScores(s) }));
const CALIBRATED_W = calibrateWeights(scoredBaseline);
sandbox.setCalibratedW(CALIBRATED_W); // computeTotal が較正重みを使うようvm内にも反映
const BASELINE_TOTALS = scoredBaseline.map(s => ({ name: s.name, total: computeTotal(s.scores, 'どてっぱん'), profit: s.profit, ebitda: s.ebitda }));

// ---- ツールのサーバーAPI ----
async function api(pathName, body) {
  const resp = await fetch(DVS_URL + pathName, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Access-Token': DVS_TOKEN },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(`${pathName} ${resp.status}: ${err.error || ''} ${err.detail || ''}`);
  }
  return resp.json();
}

// index.html の fetchCompetitors と同じ集計(件数+口コミ加重)
function aggregate(places) {
  const establishments = places.map(p => ({
    name: p.name,
    ratingCount: p.ratingCount || 0,
    category: classifyEstablishment(p),
    weight: computeWeight(p.ratingCount),
  }));
  const counts = { direct: 0, synergy: 0, neutral: 0, excluded: 0, total: establishments.length,
    directWeighted: 0, synergyWeighted: 0, neutralWeighted: 0 };
  establishments.forEach(e => {
    counts[e.category]++;
    if (e.category === 'direct') counts.directWeighted += e.weight;
    if (e.category === 'synergy') counts.synergyWeighted += e.weight;
    if (e.category === 'neutral') counts.neutralWeighted += e.weight;
  });
  counts.directWeighted = Math.round(counts.directWeighted * 10) / 10;
  counts.synergyWeighted = Math.round(counts.synergyWeighted * 10) / 10;
  counts.neutralWeighted = Math.round(counts.neutralWeighted * 10) / 10;
  return { establishments, counts };
}

async function judge(p) {
  const geo = await api('/api/places/geocode', { address: p.address });
  const lat = geo.lat, lng = geo.lng;
  const nearby = await api('/api/places/nearby', { lat, lng, radius: p.radius || 100, withDetails: true });
  const { establishments, counts } = aggregate(nearby.places || []);

  const inp = {
    ...p,
    seats: p.seats || Math.round(p.tsubo * 1.5),
    compDirect: counts.direct, compSynergy: counts.synergy, compNeutral: counts.neutral,
    compDirectWeighted: counts.directWeighted,
    compSynergyWeighted: counts.synergyWeighted,
    compNeutralWeighted: counts.neutralWeighted,
    search: p.search || 0, hire: p.hire || 'C',
  };
  const scores = computeScores(inp);
  const total = computeTotal(scores, 'どてっぱん');
  const rank = deriveRank(total);

  // 類似3店舗(画面と同じ: 総合スコア差の小さい既存店)から利益レンジ
  const near = BASELINE_TOTALS.map(r => ({ ...r, diff: Math.abs(r.total - total) }))
    .sort((a, b) => a.diff - b.diff).slice(0, 3);

  return {
    name: p.name, address: p.address, geocoded: geo.formattedAddress,
    ll: [Math.round(lat * 1e4) / 1e4, Math.round(lng * 1e4) / 1e4], // data.jsonのピン座標更新用
    sc: Math.round(total * 10) / 10, rank,
    scores: Object.fromEntries(Object.entries(scores).map(([k, v]) => [k, Math.round(v * 10) / 10])),
    counts,
    competitors: establishments.filter(e => e.category !== 'excluded').map(e => `${e.category === 'direct' ? '🍳' : e.category === 'synergy' ? '🍺' : '🍜'}${e.name}(口コミ${e.ratingCount})`),
    similarStores: near.map(r => `${r.name}(利益${Math.round(r.profit / 10000)}万)`),
    profitRange: [Math.min(...near.map(r => r.profit)), Math.max(...near.map(r => r.profit))].map(v => Math.round(v / 10000)),
  };
}

(async () => {
  const props = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  console.log('較正重み:', Object.entries(CALIBRATED_W).map(([k, v]) => `${k}${v.toFixed(1)}%`).join(' '));
  const results = [];
  for (const p of props) {
    try {
      const r = await judge(p);
      results.push(r);
      console.log(`\n■ ${r.name} → 偏差値 ${r.sc}(ランク${r.rank}) ${r.sc >= 50 ? '✅掲載' : '❌50未満'}`);
      console.log(`  軸: 需要${r.scores.pop} 競合${r.scores.comp} 家賃${r.scores.rent} 検索${r.scores.search} 採用${r.scores.hire}`);
      console.log(`  競合(100m): 🍳直撃${r.counts.direct}(加重${r.counts.directWeighted}) 🍺共食${r.counts.synergy}(加重${r.counts.synergyWeighted}) 🍜中立${r.counts.neutral}(加重${r.counts.neutralWeighted})`);
      console.log(`  類似店: ${r.similarStores.join(' / ')} → 利益目安 +${r.profitRange[0]}万〜+${r.profitRange[1]}万`);
    } catch (e) {
      results.push({ name: p.name, error: e.message });
      console.error(`\n■ ${p.name} → エラー: ${e.message}`);
    }
    await new Promise(res => setTimeout(res, 500)); // API負荷とレート制限への配慮
  }
  const outPath = inputPath.replace(/\.json$/, '') + '.result.json';
  fs.writeFileSync(outPath, JSON.stringify(results, null, 1));
  console.log(`\n結果を保存: ${outPath}`);
})();
