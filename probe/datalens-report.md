# DataLens / 物件巡回サイト 到達性・自動化事前調査レポート

- 調査日: 2026-08-14
- 実行環境: Claude Code on the web（クラウド隔離コンテナ）
- 調査範囲: 各URLのHTTPS到達性、DataLensの認証方式、自動化の実現可能性、当環境での物件サイト巡回可否
- 制約遵守: ログイン試行・パスワード推測は一切行っていません（認証情報も未保有）。また、組織のegressポリシーによる拒否（403）に対しては、README（`/root/.ccr/README.md`）の指示に従い**迂回・再試行を行っていません**。

---

## (a) 各URLの到達性一覧

すべてローカルのエージェントプロキシ（`HTTPS_PROXY=http://127.0.0.1:42135` → ポリシー適用型egressプロキシ）経由でのアクセス結果です。

| # | URL | 結果 | 判定 | 備考 |
|---|-----|------|------|------|
| 1 | https://umapro.leadlens.nowcast-app.com/property | **403（CONNECTトンネル拒否）** | ❌ 到達不可 | egressポリシーでブロック。TLSハンドシェイクまで到達せず |
| 2 | https://www.temposmart.jp | **403（CONNECTトンネル拒否）** | ❌ 到達不可 | 同上 |
| 3 | https://www.inshokuten.com | **403（CONNECTトンネル拒否）** | ❌ 到達不可 | 同上 |
| 4 | https://tempodas.com | **403（CONNECTトンネル拒否）** | ❌ 到達不可 | 同上 |
| 5 | https://places.googleapis.com | **404** | ✅ 到達可 | 接続成立。404はパス未指定/認証なしのため（＝サーバは応答している） |
| 6 | https://maps.googleapis.com | **302** | ✅ 到達可 | 接続成立。302リダイレクト応答（＝サーバは応答している） |

補足:
- 1〜4 の `000`/`403` は「サーバが落ちている」のではなく、**当実行環境のegress（外向き通信）ポリシーがホストを許可していない**ためです。プロキシがCONNECT段階で `HTTP/1.1 403 Forbidden` を返しています。
- プロキシの `recentRelayFailures` にも `connect_rejected / "gateway answered 403 to CONNECT (policy denial or upstream failure)"` として 1〜4 および `developers.google.com` が記録されていました。
- Google系（5・6）は許可リストに含まれており到達可能。DataLensのライブラリ調査で参照した `developers.google.com` はブロックされていました（`*.googleapis.com` は可、`developers.google.com` は不可という粒度）。

---

## (b) DataLensの認証方式

**当環境からはホスト（`umapro.leadlens.nowcast-app.com`）へ到達できなかったため、ログインページのHTML・JSバンドルを取得できず、認証方式は実地確認できませんでした。**

- ページHTMLの取得、内部APIベースパス（`/api/` 等）やGraphQLの有無、公開エンドポイント名の列挙は、いずれも**未実施（実施不能）**です。
- egressポリシーによる403拒否であるため、迂回・再試行は行っていません（組織ポリシー遵守）。
- ドメイン構成（`umapro`＝テナントサブドメイン + `leadlens.nowcast-app.com`＝ベンダーのSaaS基盤 = Nowcast/ナウキャスト社の「leadlens」系プロダクト）から、**マルチテナントのB2B SaaS**であることが推測されますが、これは命名からの推測であり、認証フローの実確認ではありません。

→ 認証方式（メール+パスワード / SSO / マジックリンク / reCAPTCHA有無）を確定するには、**このドメインを許可した環境**からの再調査が必要です（後述「再実行手順」参照）。

---

## (c) 自動化の実現可能性評価

前提: 現時点では DataLens 本体へ到達できていないため、以下は**一般論＋観測事実に基づく暫定評価**です。確定には到達可能な環境での追加調査が必要です。

### ヘッドレスブラウザでのログイン・データ取得
- 技術面: 当環境には Chromium + Playwright が事前構成済み（`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`）で、ヘッドレス巡回の**実行基盤自体は整っています**。
- ただし**現状の最大のボトルネックはネットワーク到達性**です。対象ドメインがegressで遮断されている限り、ヘッドレスでもアクセス不可（ブラウザもプロキシ経由のため同じく403）。
- SaaSの利用規約・スクレイピング可否の確認が別途必要。マルチテナントSaaSはbot対策（reCAPTCHA/デバイスフィンガープリント/レート制限）を備えることが多く、ヘッドレス自動ログインは規約・技術の両面で不確実性が残ります。

### APIを直接叩く方式
- DataLensが公開/契約者向けAPIを提供しているかは**未確認**（HTML/JS未取得のため）。
- 一般に、ヘッドレスのフォーム自動化よりも、ベンダー提供の正規API・データエクスポート機能・CSV/バルク出力を使う方が、規約適合性・安定性ともに優れます。**まずベンダー（Nowcast社）に自動連携用API/エクスポートの有無を問い合わせるのが最短かつ最も堅実**です。

### 総合評価（暫定）
| 観点 | 現時点の見立て |
|------|----------------|
| ネットワーク到達 | 現環境では**不可**（要ポリシー変更） |
| 実行基盤（ブラウザ/Playwright） | 準備済み・良好 |
| ヘッドレス自動ログイン | 到達確保後に要検証（bot対策・規約リスクあり） |
| 直接API利用 | 有無未確認。**ベンダー確認を推奨** |
| 推奨アプローチ | ①ベンダーへ正規API/エクスポート照会 → ②無ければ到達許可のうえヘッドレス検証、の順 |

---

## (d) この環境で物件サイト巡回が可能かの判定

**判定: 現状の当実行環境では、対象4サイト（DataLens・temposmart・inshokuten・tempodas）の巡回は不可。**

- 理由: これら4ドメインが**組織のegressポリシーで遮断**されている（CONNECT段階403）。ブラウザ/Playwright等の実行基盤は整っているが、通信そのものが到達しない。
- 到達できているのは `*.googleapis.com`（Places/Maps）のみ。**Google系APIを用いた住所ジオコーディング・地点情報取得は当環境からでも実行可能**。
- 巡回を実現するには、次のいずれかが必要:
  1. **egress許可リストへ対象ドメインを追加**（環境作成者/管理者が https://claude.ai/code の環境設定で調整）。
  2. または、**対象ドメインへの到達が許可された別環境／ネットワーク**でパイプラインを実行。

### 参考: ブロック中ドメイン（許可リスト追加候補）
```
umapro.leadlens.nowcast-app.com
www.temposmart.jp
www.inshokuten.com
tempodas.com
（必要に応じて）developers.google.com
```

### 再実行手順（到達許可後）
上記を許可した環境で、本レポートの (b) を完了させる:
1. `curl -sS https://umapro.leadlens.nowcast-app.com/property` でログインページHTMLを取得。
2. HTML内の `<form>`・input（`type=email`/`password`）、SSO/OAuthリンク、`grecaptcha`/`hcaptcha` の有無を確認。
3. 参照JSバンドル（`<script src=...>`）を取得し、`/api/`・`/graphql`・`fetch(`・`axios`・エンドポイント文字列を grep してベースパス/エンドポイントを列挙。
4. ※ログイン試行・パスワード推測は引き続き禁止。

---

## 付録: 実行環境ネットワーク構成の要点
- 外向きHTTPSはローカルプロキシ `127.0.0.1:42135`（`HTTPS_PROXY`）→ ポリシー適用型egressプロキシを経由。TLSは再終端され、CAバンドル `/root/.ccr/ca-bundle.crt` を信頼する構成。
- `selective/toolScoped=false`、`enabled=true`。到達可否は**ドメイン許可リスト**で制御。
- 403/407（ポリシー拒否）は迂回・再試行せず報告する運用（READMEの明示指示）。本調査もこれを遵守。
