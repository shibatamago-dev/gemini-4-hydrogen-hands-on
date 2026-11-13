# Gemini 4 Hydrogen — hands-on comparison code

Gemini 4 Hydrogen（`gemini-4-hydrogen`）と Gemini 3.8 Flash（`gemini-3.8-flash`）に同じ課題を投げて、返ってきたコードや文章を機械的に採点したときの、課題・コード・結果です。

Zenn記事（下書き）の検証部分で使ったものと、課題の全文はここで見られます。

- 記事: [Gemini 4 Hydrogenを実際に動かしてみた](https://github.com/shibatamago-dev/zenn-content/blob/main/articles/gemini-4-hydrogen-hands-on.md)（zenn-content リポジトリ内）

## 課題（全部で4つ＋追加1つ）

条件は temperature 0、思考レベル high、出力上限 8,192 トークンで両モデル共通です。

| 課題 | 内容 | 採点方法 |
|---|---|---|
| T1 | バグ入りの移動平均関数を直す | 返ってきたコードを実行し、テスト5件 |
| T2 | "1h30m" のような文字列を秒に直す関数を書く | 返ってきたコードを実行し、テスト8件 |
| T3 | プロジェクトのメモから予算・期限などを JSON で抽出 | 正解と5項目を照合 |
| T4 | 価格が書かれていない商品説明から決まった形式で抽出 | 形式と「価格を作っていないか」の4項目 |
| T2追加 | T2 を Hydrogen の思考レベル xhigh でもう一度 | T2 と同じ |

課題の全文（プロンプト）と採点コードは `standalone_compare.py` の中にあります。

## 結果（2026-11-13、results.json）

Hydrogen（high）は T1 5/5、T2 8/8、T3 5/5、T4 4/4 でした。T2 を xhigh で解かせた回は、思考トークンが 8,189 / 8,192 を使い切り、答えの本文が空になりました（終了理由 MAX_TOKENS）。思考トークンは出力上限の中から消費されるので、xhigh を使うときは出力上限を大きめに取る必要があります。

Flash 側はこの実行では測れていません。503（需要過多）が続いたあと 429 になり、無料枠の上限（gemini-3.8-flash は 1 日 20 回まで）に当たりました。枠の回復後に再実行して、結果を更新します。

`results.json` の所要時間は Muse の実行環境から測ったもので、接続が止まることがある環境の数字です。モデルの応答速度として読まないでください。

## 自分の環境で試すには

Google AI Studio で API キーを取って（無料枠で可）、環境変数に入れて実行します。キーをファイルに書かないでください。

```bash
export GEMINI_API_KEY="自分のAPIキー"
python3 standalone_compare.py
```

Windows（PowerShell）:

```powershell
$env:GEMINI_API_KEY = "自分のAPIキー"
python standalone_compare.py
```

実行すると `results.json` と `raw/` が上書きされます。同梱の結果を残したい場合は、先に名前を変えてください。

注意:

- 無料枠では、入力した内容が Google の製品改善に使われることがあります。機密文書は投げないでください
- Flash の無料枠は 1 日 20 回までと小さく、503 などへのリトライも回数に入ります

## ファイル

| ファイル | 内容 |
|---|---|
| `standalone_compare.py` | 課題・採点・実行の全部（キーなしでは動きません） |
| `results.json` | 2026-11-13 の実行記録（スコア、トークン数、エラー全文） |
| `raw/` | 各回の API レスポンス全文 |
| `LICENSE` | MIT |
