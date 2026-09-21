# airpre

地区ごとの気圧変化サイト。エージェントはこのファイルを作業前に読む。

## 方針

- 自動実行してよい処理は `make -f Makefile.agent <target>` だけを使う。
- `.cursor/permissions.json` の allowlist には依存しない。
- Python ランタイムとパッケージは **uv** が管理する。mise が入れるのは **uv だけ**。
- Python は `.python-version` の安定最新版。3.12 に固定しない。
- ドキュメントでは特定の地区名を前提に書かない。地区は `src/airpre/areas.py` の定義が正。

## 構成

| パス | 役割 |
| --- | --- |
| `src/airpre/areas.py` | 地区と観測点の定義。追加はここにエントリを足す |
| `src/airpre/fetch.py` | 定義済み地区の10分値を取得し `data/<area-id>/` に蓄積 |
| `data/areas.json` | サイトが読む地区カタログ |
| `data/<area-id>/latest.json` | その地区の直近14日分 |
| `data/<area-id>/archive/YYYY-MM-DD.json` | 日別アーカイブ |
| `site/` | GitHub Pages に載せる静的サイト |
| `docker-compose.yml` | ローカル確認用 nginx |

## データ

- 出典は気象庁の公開 JSON。API キーは不要。
- 取得ジョブは定義済みの全地区を処理する。観測ファイルがまだ無い地区はカタログ上 `hasData: false`。
- 気象庁の地点 API は数日分しか返さない。履歴を残すため GitHub Actions が1時間ごとに、不足している3時間スロットだけ取得して `data/` へ commit する。
- データ更新 workflow は Pages をデプロイしない。本番サイトは `raw.githubusercontent.com` の `data/` を読む。
- ローカルサイトはホスト名が `localhost` のとき `/data/` を読む。

## コマンド

初回や依存更新後:

```sh
make -f Makefile.agent setup
```

実装後の確認:

```sh
make -f Makefile.agent check
make -f Makefile.agent fetch-data
make -f Makefile.agent serve-up
```

ブラウザ確認 URL は `http://127.0.0.1:8080/`。停止は `make -f Makefile.agent serve-down`。

## 実装上の約束

- 取得処理にサードパーティ HTTP ライブラリを足さない（標準ライブラリの `urllib`）。
- Pages 用 workflow の path filter に `data/**` を入れない。
- サイトはビルドせず、`site/` の静的ファイルだけをデプロイする。
- 地区追加は `AREAS` への追加で完結させる。サイトは `areas.json` を見て地区一覧を描画する。
