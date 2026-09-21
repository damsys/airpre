# airpre

地区ごとの気圧変化を、気象庁の観測アーカイブからグラフ表示する静的サイトです。

## 見る

本番は GitHub Pages（リポジトリ設定で Source を GitHub Actions にする）を想定しています。

```text
https://damsys.github.io/airpre/
```

サイト本体はデプロイ済みの静的ファイルで、気圧データは毎回 Pages を出し直さず
`raw.githubusercontent.com` 上の `data/` を読みます。

## データ

- 出典は [気象庁 AMeDAS](https://www.jma.go.jp/bosai/amedas/) の公開 JSON。API キーは不要。
- 地区の定義は `src/airpre/areas.py`。取得対象を増やすときはここにエントリを足す。
- 観測は `data/<area-id>/` に蓄積する。カタログは `data/areas.json`。
- 地点 API は直近数日分しか返さないため、GitHub Actions が10分ごとに取得して commit する。
- データ更新 workflow は Pages をデプロイしない。

都度ブラウザから気象庁へ取りに行く方式は、CORS・履歴の短さ・障害時の空白の点で不利なため採用していません。

## ローカル

ツールはリポジトリの `mise.toml` で uv を入れ、Python と依存は uv が管理します。

```sh
make -f Makefile.agent setup
make -f Makefile.agent fetch-data
make -f Makefile.agent serve-up
```

[http://127.0.0.1:8080/](http://127.0.0.1:8080/) で、保存済みの `data/` を表示します。
