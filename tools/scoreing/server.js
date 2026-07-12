/**
 * どてっぱん 物件スコア判定ツール - Railway デプロイ用サーバー
 * v3.0.0: スコアエンジン刷新対応(フロントのみ変更・サーバーはv2.7.1相当)
 *
 * 機能:
 *  - Basic認証によるアクセス制限
 *  - 静的HTMLファイルの配信
 *  - 履歴API (GET/POST/DELETE) - Railway Volume に永続化
 *  - ベースライン競合分類API
 *  - Google Places API プロキシ (Autocomplete / Details / Nearby / Photo / Geocode)
 *  - コスト最適化: Session Token / Field Mask / Cache
 *  - v2.7.1: Google API エラーメッセージをフロントに正確に伝播
 *
 * 環境変数:
 *  - BASIC_AUTH_USER: ログインID (デフォルト: umapro)
 *  - BASIC_AUTH_PASSWORD: ログインパスワード (必須)
 *  - GOOGLE_API_KEY: Google Cloud API キー (Places APIを有効化したもの・必須)
 *  - PORT: サーバーポート (Railwayが自動設定)
 *  - DATA_DIR: データ保存ディレクトリ (デフォルト: /data)
 */

const express = require('express');
const basicAuth = require('express-basic-auth');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

// ===========================================================
// 環境変数チェック
// ===========================================================
const AUTH_USER = process.env.BASIC_AUTH_USER || 'umapro';
const AUTH_PASSWORD = process.env.BASIC_AUTH_PASSWORD;
// 無人自動化用アクセストークン（任意）。設定時のみ有効。
// cookie(dvs_token) か X-Access-Token ヘッダがこの値と一致すればBasic認証をスキップする。
// 未設定なら従来どおり純粋なBasic認証のまま（安全側デフォルト）。
const ACCESS_TOKEN = process.env.ACCESS_TOKEN;
const GOOGLE_API_KEY = process.env.GOOGLE_API_KEY;
const DATA_DIR = process.env.DATA_DIR || '/data';
const HISTORY_FILE = path.join(DATA_DIR, 'history.json');
const BASELINE_COMP_FILE = path.join(DATA_DIR, 'baseline_competitors.json');
const CACHE_FILE = path.join(DATA_DIR, 'places_cache.json');

if (!AUTH_PASSWORD) {
  console.error('❌ ERROR: BASIC_AUTH_PASSWORD 環境変数が設定されていません');
  process.exit(1);
}

if (!GOOGLE_API_KEY) {
  console.warn('⚠ WARNING: GOOGLE_API_KEY が未設定です。Places APIは動作しません。');
  console.warn('   Google Cloud で Places API (New) と Geocoding API を有効化し、');
  console.warn('   Railway の Variables で GOOGLE_API_KEY を設定してください。');
}

// ===========================================================
// データディレクトリの初期化
// ===========================================================
function initDataDir() {
  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
      console.log(`📁 データディレクトリを作成: ${DATA_DIR}`);
    }
    if (!fs.existsSync(HISTORY_FILE)) {
      fs.writeFileSync(HISTORY_FILE, JSON.stringify({ entries: [] }, null, 2));
    }
  } catch (err) {
    console.error(`⚠ データディレクトリ初期化失敗: ${err.message}`);
  }
}
initDataDir();

// ===========================================================
// ファイルベースの簡易キャッシュ（Places API コスト削減）
// TTL: 24時間
// ===========================================================
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
let placesCache = { entries: {} };

function loadCache() {
  try {
    if (fs.existsSync(CACHE_FILE)) {
      placesCache = JSON.parse(fs.readFileSync(CACHE_FILE, 'utf-8'));
    }
  } catch (err) { placesCache = { entries: {} }; }
}
loadCache();

function saveCache() {
  try {
    const now = Date.now();
    Object.keys(placesCache.entries).forEach(k => {
      if (now - placesCache.entries[k].savedAt > CACHE_TTL_MS) {
        delete placesCache.entries[k];
      }
    });
    fs.writeFileSync(CACHE_FILE, JSON.stringify(placesCache, null, 2));
  } catch (err) { /* noop */ }
}

function cacheGet(key) {
  const entry = placesCache.entries[key];
  if (!entry) return null;
  if (Date.now() - entry.savedAt > CACHE_TTL_MS) {
    delete placesCache.entries[key];
    return null;
  }
  return entry.data;
}

function cacheSet(key, data) {
  placesCache.entries[key] = { data, savedAt: Date.now() };
  clearTimeout(cacheSet._t);
  cacheSet._t = setTimeout(saveCache, 3000);
}

// ===========================================================
// 履歴ファイル操作
// ===========================================================
function readHistory() {
  try {
    if (!fs.existsSync(HISTORY_FILE)) return { entries: [] };
    return JSON.parse(fs.readFileSync(HISTORY_FILE, 'utf-8'));
  } catch (err) { return { entries: [] }; }
}
function writeHistory(data) {
  try {
    fs.writeFileSync(HISTORY_FILE, JSON.stringify(data, null, 2));
    return true;
  } catch (err) { return false; }
}
function readBaselineCompetitors() {
  try {
    if (!fs.existsSync(BASELINE_COMP_FILE)) return { stores: {}, updatedAt: null };
    return JSON.parse(fs.readFileSync(BASELINE_COMP_FILE, 'utf-8'));
  } catch (err) { return { stores: {}, updatedAt: null }; }
}
function writeBaselineCompetitors(data) {
  try {
    fs.writeFileSync(BASELINE_COMP_FILE, JSON.stringify(data, null, 2));
    return true;
  } catch (err) { return false; }
}

// ===========================================================
// ヘルスチェック (認証なし)
// ===========================================================
app.get('/health', (req, res) => {
  const history = readHistory();
  res.status(200).json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    version: '3.0.0',
    historyEntries: history.entries?.length || 0,
    volumeMounted: fs.existsSync(DATA_DIR),
    googleApiConfigured: !!GOOGLE_API_KEY,
    cacheEntries: Object.keys(placesCache.entries).length
  });
});

// ===========================================================
// アクセストークンによるログイン省略（無人自動化用）
// ===========================================================
function parseCookies(req) {
  const h = req.headers.cookie || '';
  const out = {};
  h.split(';').forEach(p => {
    p = p.trim();
    if (!p) return;
    const i = p.indexOf('=');
    if (i < 0) return;
    out[decodeURIComponent(p.slice(0, i))] = decodeURIComponent(p.slice(i + 1));
  });
  return out;
}

// 一度だけトークンを入力してcookieに保存するページ（認証不要）。
// トークンはクライアント側でcookieに書き込むだけ。URLにもサーバーログにも残さない。
app.get('/unlock', (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.send(`<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>アクセス設定 - どてっぱん物件スコア判定</title>
  <style>body{font-family:system-ui,sans-serif;max-width:420px;margin:60px auto;padding:0 20px;color:#1F3A5F}
  h1{font-size:18px}input{width:100%;padding:10px;font-size:16px;box-sizing:border-box;margin:8px 0;border:1px solid #ccc;border-radius:8px}
  button{width:100%;padding:12px;font-size:16px;background:#E07B39;color:#fff;border:0;border-radius:8px;cursor:pointer}
  p{font-size:13px;color:#555;line-height:1.6}</style></head>
  <body><h1>🔓 アクセストークン設定</h1>
  <p>Railwayの環境変数 <code>ACCESS_TOKEN</code> に設定した値を入力してください。この端末のブラウザに1年間保存され、次回以降ログイン不要になります。</p>
  <input id="t" type="password" placeholder="アクセストークン" autocomplete="off">
  <button id="b">保存してツールを開く</button>
  <p id="m"></p>
  <script>
    document.getElementById('b').onclick=function(){
      var v=document.getElementById('t').value.trim();
      if(!v){document.getElementById('m').textContent='トークンを入力してください';return;}
      var secure=location.protocol==='https:'?'; secure':'';
      document.cookie='dvs_token='+encodeURIComponent(v)+'; path=/; max-age=31536000; samesite=lax'+secure;
      location.href='/';
    };
    document.getElementById('t').addEventListener('keydown',function(e){if(e.key==='Enter')document.getElementById('b').click();});
  </script></body></html>`);
});

// ===========================================================
// Basic認証（トークン一致時はスキップ）
// ===========================================================
const basicAuthMw = basicAuth({
  users: { [AUTH_USER]: AUTH_PASSWORD },
  challenge: true,
  realm: 'Doteppan Property Scoring Tool'
});

app.use((req, res, next) => {
  if (ACCESS_TOKEN) {
    const supplied = parseCookies(req)['dvs_token'] || req.headers['x-access-token'];
    if (supplied && supplied === ACCESS_TOKEN) return next(); // 認証スキップ
  }
  return basicAuthMw(req, res, next);
});

app.use(express.json({ limit: '1mb' }));

// ===========================================================
// 履歴API
// ===========================================================
app.get('/api/history', (req, res) => res.json(readHistory()));

app.post('/api/history', (req, res) => {
  try {
    const entry = req.body;
    if (!entry || typeof entry !== 'object') return res.status(400).json({ error: 'Invalid entry' });

    const data = readHistory();
    if (!Array.isArray(data.entries)) data.entries = [];

    const newEntry = {
      id: Date.now().toString(36) + Math.random().toString(36).substr(2, 5),
      createdAt: new Date().toISOString(),
      ...entry
    };
    data.entries.unshift(newEntry);
    if (data.entries.length > 500) data.entries = data.entries.slice(0, 500);

    if (!writeHistory(data)) return res.status(500).json({ error: 'Failed to save' });
    res.status(201).json(newEntry);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.delete('/api/history/:id', (req, res) => {
  try {
    const id = req.params.id;
    const data = readHistory();
    if (!Array.isArray(data.entries)) return res.status(404).json({ error: 'Not found' });

    const before = data.entries.length;
    data.entries = data.entries.filter(e => e.id !== id);
    if (data.entries.length === before) return res.status(404).json({ error: 'Entry not found' });
    if (!writeHistory(data)) return res.status(500).json({ error: 'Failed to save' });
    res.json({ success: true, deletedId: id });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ===========================================================
// ベースライン競合API
// ===========================================================
app.get('/api/baseline-competitors', (req, res) => res.json(readBaselineCompetitors()));

app.post('/api/baseline-competitors', (req, res) => {
  try {
    const stores = req.body?.stores;
    if (!stores || typeof stores !== 'object') return res.status(400).json({ error: 'Invalid payload' });
    const data = {
      stores,
      updatedAt: new Date().toISOString(),
      updatedBy: req.body.updatedBy || ''
    };
    if (!writeBaselineCompetitors(data)) return res.status(500).json({ error: 'Failed to save' });
    res.status(201).json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ===========================================================
// Google Places API プロキシ (v2.7.1: エラー伝播強化)
// ===========================================================

function googleApiKeyCheck(res) {
  if (!GOOGLE_API_KEY) {
    res.status(503).json({
      error: 'Google APIキー未設定',
      detail: 'Railway の Variables で GOOGLE_API_KEY を設定してください。'
    });
    return false;
  }
  return true;
}

/**
 * Google API のエラーレスポンスから、人間に分かりやすいメッセージを生成
 * 特に API キー制限(HTTPリファラー)による REQUEST_DENIED を検知
 */
function interpretGoogleError(status, errorBody) {
  let msg = errorBody;
  let hint = '';
  let reason = 'unknown';

  try {
    const parsed = typeof errorBody === 'string' ? JSON.parse(errorBody) : errorBody;
    msg = parsed?.error?.message || msg;
    const googleStatus = parsed?.error?.status || '';
    const details = parsed?.error?.details || [];

    // REQUEST_DENIED: ほぼAPIキー制限の問題
    if (googleStatus === 'PERMISSION_DENIED' || status === 403) {
      reason = 'api_key_denied';
      hint = 'APIキーの「アプリケーションの制限」がHTTPリファラーになっている可能性があります。'
        + 'このツールはサーバー経由でGoogle APIを呼ぶため、HTTPリファラー制限だと必ず失敗します。'
        + 'Google Cloud Console → APIとサービス → 認証情報 → APIキー → 「アプリケーションの制限」を「なし」に変更してください。';
    } else if (googleStatus === 'NOT_FOUND' || status === 404) {
      reason = 'not_found';
      hint = 'Google側で該当データが見つかりませんでした。';
    } else if (status === 400) {
      reason = 'bad_request';
      hint = `リクエストが不正です: ${msg}`;
    } else if (status === 429) {
      reason = 'rate_limit';
      hint = 'APIクォータ超過です。少し待ってから再試行してください。';
    }

    // APIが有効化されていない場合の検知
    const reasonStr = JSON.stringify(details);
    if (reasonStr.includes('SERVICE_DISABLED') || msg.includes('has not been used')) {
      reason = 'api_not_enabled';
      hint = 'Places API (New) または Geocoding API がGoogle Cloudで有効化されていません。'
        + 'Google Cloud Console → APIとサービス → ライブラリで両方を有効化してください。';
    }
  } catch (e) { /* パース失敗はそのまま */ }

  return { status, message: msg, hint, reason };
}

// 1. Autocomplete: 住所・場所のサジェスト
app.post('/api/places/autocomplete', async (req, res) => {
  if (!googleApiKeyCheck(res)) return;
  try {
    const { input, sessionToken, types } = req.body;
    if (!input || input.length < 2) {
      return res.json({ suggestions: [] });
    }

    const cacheKey = `ac:${input}:${types || ''}`;
    const cached = cacheGet(cacheKey);
    if (cached) return res.json({ ...cached, fromCache: true });

    const body = {
      input,
      languageCode: 'ja',
      regionCode: 'JP'
    };
    if (sessionToken) body.sessionToken = sessionToken;
    // types='address' が指定されたら住所系に絞る
    // ※何も指定しない場合はデフォルト(施設+住所の両方)で返す
    if (types === 'address') {
      body.includedPrimaryTypes = ['street_address', 'premise', 'subpremise', 'route', 'locality', 'sublocality'];
    }

    const resp = await fetch('https://places.googleapis.com/v1/places:autocomplete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY
      },
      body: JSON.stringify(body)
    });

    if (!resp.ok) {
      const errText = await resp.text();
      const err = interpretGoogleError(resp.status, errText);
      console.error('Autocomplete error:', resp.status, err.reason, errText);
      return res.status(resp.status >= 500 ? 502 : resp.status).json({
        error: 'Autocomplete failed',
        googleStatus: resp.status,
        reason: err.reason,
        detail: err.message,
        hint: err.hint
      });
    }

    const data = await resp.json();
    const suggestions = (data.suggestions || []).map(s => ({
      placeId: s.placePrediction?.placeId,
      text: s.placePrediction?.text?.text,
      mainText: s.placePrediction?.structuredFormat?.mainText?.text,
      secondaryText: s.placePrediction?.structuredFormat?.secondaryText?.text,
      types: s.placePrediction?.types || []
    })).filter(s => s.placeId);

    const result = { suggestions };
    cacheSet(cacheKey, result);
    res.json(result);
  } catch (err) {
    console.error('Autocomplete exception:', err);
    res.status(500).json({ error: 'Autocomplete failed', detail: err.message });
  }
});

// 2. Place Details
app.post('/api/places/details', async (req, res) => {
  if (!googleApiKeyCheck(res)) return;
  try {
    const { placeId, sessionToken, fields } = req.body;
    if (!placeId) return res.status(400).json({ error: 'placeId is required' });

    const cacheKey = `details:${placeId}:${fields || 'basic'}`;
    const cached = cacheGet(cacheKey);
    if (cached) return res.json({ ...cached, fromCache: true });

    let fieldMask = 'id,displayName,location,formattedAddress,primaryType,primaryTypeDisplayName,types';
    if (fields === 'full') {
      fieldMask += ',rating,userRatingCount,regularOpeningHours,photos,priceLevel';
    }

    const url = `https://places.googleapis.com/v1/places/${placeId}`;
    const headers = {
      'X-Goog-Api-Key': GOOGLE_API_KEY,
      'X-Goog-FieldMask': fieldMask
    };
    if (sessionToken) headers['X-Goog-Session-Token'] = sessionToken;

    const resp = await fetch(url, { headers });
    if (!resp.ok) {
      const errText = await resp.text();
      const err = interpretGoogleError(resp.status, errText);
      console.error('Details error:', resp.status, err.reason, errText);
      return res.status(resp.status >= 500 ? 502 : resp.status).json({
        error: 'Details failed',
        googleStatus: resp.status,
        reason: err.reason,
        detail: err.message,
        hint: err.hint
      });
    }

    const data = await resp.json();
    const result = {
      placeId: data.id,
      name: data.displayName?.text || '',
      lat: data.location?.latitude,
      lng: data.location?.longitude,
      address: data.formattedAddress || '',
      primaryType: data.primaryType || '',
      primaryTypeDisplayName: data.primaryTypeDisplayName?.text || '',
      types: data.types || [],
      rating: data.rating || null,
      ratingCount: data.userRatingCount || 0,
      priceLevel: data.priceLevel || '',
      openingHours: data.regularOpeningHours?.weekdayDescriptions || [],
      photos: (data.photos || []).slice(0, 3).map(p => ({ name: p.name, widthPx: p.widthPx, heightPx: p.heightPx }))
    };
    cacheSet(cacheKey, result);
    res.json(result);
  } catch (err) {
    console.error('Details exception:', err);
    res.status(500).json({ error: 'Details failed', detail: err.message });
  }
});

// 3. Nearby Search
app.post('/api/places/nearby', async (req, res) => {
  if (!googleApiKeyCheck(res)) return;
  try {
    const { lat, lng, radius = 100, withDetails = false } = req.body;
    if (typeof lat !== 'number' || typeof lng !== 'number') {
      return res.status(400).json({ error: 'lat/lng required' });
    }

    const cacheKey = `nearby:${lat.toFixed(5)}:${lng.toFixed(5)}:${radius}:${withDetails?'full':'basic'}`;
    const cached = cacheGet(cacheKey);
    if (cached) return res.json({ ...cached, fromCache: true });

    const includedTypes = [
      'restaurant', 'bar', 'cafe', 'fast_food_restaurant',
      'japanese_restaurant', 'sushi_restaurant', 'ramen_restaurant',
      'italian_restaurant', 'chinese_restaurant', 'korean_restaurant',
      'thai_restaurant', 'vietnamese_restaurant', 'mexican_restaurant',
      'french_restaurant', 'indian_restaurant',
      'barbecue_restaurant', 'steak_house', 'pizza_restaurant',
      'hamburger_restaurant', 'brunch_restaurant', 'breakfast_restaurant',
      'pub', 'wine_bar', 'meal_takeaway'
    ];

    let fieldMask = 'places.id,places.displayName,places.primaryType,places.primaryTypeDisplayName,places.types,places.location';
    if (withDetails) {
      fieldMask += ',places.rating,places.userRatingCount,places.photos,places.priceLevel';
    }

    const body = {
      includedTypes,
      maxResultCount: 20,
      locationRestriction: {
        circle: {
          center: { latitude: lat, longitude: lng },
          radius
        }
      },
      languageCode: 'ja',
      regionCode: 'JP'
    };

    const resp = await fetch('https://places.googleapis.com/v1/places:searchNearby', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': fieldMask
      },
      body: JSON.stringify(body)
    });

    if (!resp.ok) {
      const errText = await resp.text();
      const err = interpretGoogleError(resp.status, errText);
      console.error('Nearby error:', resp.status, err.reason, errText);
      return res.status(resp.status >= 500 ? 502 : resp.status).json({
        error: 'Nearby failed',
        googleStatus: resp.status,
        reason: err.reason,
        detail: err.message,
        hint: err.hint
      });
    }

    const data = await resp.json();
    const places = (data.places || []).map(p => ({
      placeId: p.id,
      name: p.displayName?.text || '(名称不明)',
      primaryType: p.primaryType || '',
      primaryTypeDisplayName: p.primaryTypeDisplayName?.text || '',
      types: p.types || [],
      lat: p.location?.latitude,
      lng: p.location?.longitude,
      rating: p.rating || null,
      ratingCount: p.userRatingCount || 0,
      priceLevel: p.priceLevel || '',
      photos: (p.photos || []).slice(0, 1).map(ph => ({ name: ph.name }))
    }));

    const result = { places };
    cacheSet(cacheKey, result);
    res.json(result);
  } catch (err) {
    console.error('Nearby exception:', err);
    res.status(500).json({ error: 'Nearby failed', detail: err.message });
  }
});

// 4. Photo: 写真のプロキシ取得 (APIキーを隠蔽)
app.get('/api/places/photo/:photoName(*)', async (req, res) => {
  if (!googleApiKeyCheck(res)) return;
  try {
    const photoName = req.params.photoName;
    const maxWidth = Math.min(parseInt(req.query.maxWidth) || 200, 400);

    const url = `https://places.googleapis.com/v1/${photoName}/media?maxWidthPx=${maxWidth}&key=${GOOGLE_API_KEY}`;
    const resp = await fetch(url);

    if (!resp.ok) {
      return res.status(resp.status).send('Photo fetch failed');
    }

    res.setHeader('Content-Type', resp.headers.get('Content-Type') || 'image/jpeg');
    res.setHeader('Cache-Control', 'public, max-age=86400');
    const buffer = Buffer.from(await resp.arrayBuffer());
    res.send(buffer);
  } catch (err) {
    console.error('Photo error:', err);
    res.status(500).send('Photo error');
  }
});

// 5. Geocode: 住所→緯度経度
app.post('/api/places/geocode', async (req, res) => {
  if (!googleApiKeyCheck(res)) return;
  try {
    const { address } = req.body;
    if (!address) return res.status(400).json({ error: 'address required' });

    const cacheKey = `geocode:${address}`;
    const cached = cacheGet(cacheKey);
    if (cached) return res.json({ ...cached, fromCache: true });

    const url = `https://maps.googleapis.com/maps/api/geocode/json?address=${encodeURIComponent(address)}&region=jp&language=ja&key=${GOOGLE_API_KEY}`;
    const resp = await fetch(url);

    if (!resp.ok) {
      const errText = await resp.text();
      const err = interpretGoogleError(resp.status, errText);
      console.error('Geocode HTTP error:', resp.status, err.reason, errText);
      return res.status(resp.status >= 500 ? 502 : resp.status).json({
        error: 'Geocode failed',
        googleStatus: resp.status,
        reason: err.reason,
        detail: err.message,
        hint: err.hint
      });
    }

    const data = await resp.json();

    // v2.7.1: Googleの status を正確に分類
    if (data.status === 'REQUEST_DENIED') {
      console.error('Geocode REQUEST_DENIED:', data.error_message || '');
      return res.status(403).json({
        error: 'APIキー拒否',
        reason: 'api_key_denied',
        detail: data.error_message || 'Google Geocoding API からアクセスが拒否されました',
        hint: 'APIキーの「アプリケーションの制限」がHTTPリファラーになっている可能性があります。'
          + 'このツールはサーバー経由でGoogle APIを呼ぶため、HTTPリファラー制限だと必ず失敗します。'
          + 'Google Cloud Console → 認証情報 → APIキー → 「アプリケーションの制限」を「なし」に変更してください。'
      });
    }
    if (data.status === 'OVER_QUERY_LIMIT') {
      return res.status(429).json({
        error: 'クォータ超過',
        reason: 'rate_limit',
        detail: data.error_message || '',
        hint: 'しばらく待ってから再試行してください。'
      });
    }
    if (data.status === 'ZERO_RESULTS' || !data.results?.length) {
      return res.status(404).json({
        error: '住所が見つかりません',
        reason: 'not_found',
        detail: `Googleは住所「${address}」を見つけられませんでした`,
        hint: '番地を追加したり、建物名を外したりしてみてください。'
      });
    }
    if (data.status !== 'OK') {
      return res.status(500).json({
        error: 'Geocode failed',
        reason: 'unknown',
        detail: `Google status: ${data.status}`,
        hint: data.error_message || ''
      });
    }

    const r = data.results[0];
    const result = {
      lat: r.geometry.location.lat,
      lng: r.geometry.location.lng,
      formattedAddress: r.formatted_address
    };
    cacheSet(cacheKey, result);
    res.json(result);
  } catch (err) {
    console.error('Geocode exception:', err);
    res.status(500).json({ error: 'Geocode failed', detail: err.message });
  }
});

// ===========================================================
// 静的ファイル配信
// ===========================================================
app.use(express.static(path.join(__dirname), {
  extensions: ['html'],
  index: 'index.html',
  setHeaders: (res, filePath) => {
    if (filePath.endsWith('.html')) {
      res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    } else {
      res.setHeader('Cache-Control', 'public, max-age=3600');
    }
  }
}));

// ===========================================================
// 404ハンドラ
// ===========================================================
app.use((req, res) => {
  res.status(404).send(`
    <html lang="ja"><head><meta charset="UTF-8"><title>404</title></head>
    <body style="font-family:sans-serif;text-align:center;padding:60px">
      <h1 style="color:#1F3A5F">404 Not Found</h1>
      <p><a href="/" style="color:#E07B39">トップへ戻る</a></p>
    </body></html>
  `);
});

// ===========================================================
// サーバー起動
// ===========================================================
app.listen(PORT, () => {
  console.log(`✅ どてっぱん 物件スコア判定ツール v3.0.0`);
  console.log(`   🔐 Basic認証: ${AUTH_USER} / ********`);
  console.log(`   🎫 アクセストークン(無人通過): ${ACCESS_TOKEN ? '✅ 有効 (/unlock で登録)' : '❌ 未設定(純Basic認証)'}`);
  console.log(`   📁 データ保存: ${DATA_DIR}`);
  console.log(`   🌐 Listening on port ${PORT}`);
  console.log(`   🗺  Google API: ${GOOGLE_API_KEY ? '✅ 設定済' : '❌ 未設定'}`);
  console.log(`   💾 Cache entries: ${Object.keys(placesCache.entries).length}`);
});
