#!/bin/bash
# 巡回(テンポスマート＋テナントショップ)→判定→data.json追加 の一括実行。
# 使い方: GOOGLE_API_KEY=<key> bash tools/crawl/run.sh
set -e
cd "$(dirname "$0")/../.."
python3 tools/crawl/temposmart.py         # 首都圏+関西(candidates.json 新規作成)
python3 tools/crawl/tshop.py || true      # 滋賀(テナントショップ・candidates.json へ追記。失敗しても続行)
python3 tools/crawl/geocode_census.py
node tools/crawl/judge_add.js "$(date +%Y-%m-%d)"
python3 hungree/build.py
echo "巡回・判定・反映 完了"
