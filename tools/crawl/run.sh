#!/bin/bash
# テンポスマート巡回→判定→data.json追加 の一括実行。
# 使い方: GOOGLE_API_KEY=<key> bash tools/crawl/run.sh
set -e
cd "$(dirname "$0")/../.."
python3 tools/crawl/temposmart.py
python3 tools/crawl/geocode_census.py
node tools/crawl/judge_add.js "$(date +%Y-%m-%d)"
python3 hungree/build.py
echo "巡回・判定・反映 完了"
