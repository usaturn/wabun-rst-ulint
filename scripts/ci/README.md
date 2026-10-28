# 開発時の検証

Python 3.14 以上、uv、および PATH 上の Node.js 24.22.1 以降の 24.x が必要です。
Node.js は開発環境で別途インストールしてください。CI は同系列の修正版を明示的に導入します。
CLI 本体の利用に Node.js は必要ありません。

リポジトリの root で実行します。

```bash
./scripts/ci/verify.sh full
```

この入口は Node.js の版と実行ファイルを表示し、未対応の版や Node.js がない環境では停止します。
Pyright に PATH 上の Node.js を使わせ、wheel 同梱版や nodeenv への暗黙の切り替えを避けます。
開発中に `uv run --locked pyright src` を直接呼ぶ場合も、同じ修正版を PATH に用意してください。
版のガードを含む最終確認には上の検証入口を使います。

`pyright[nodejs]` は使用しません。これが持ち込む `nodejs-wheel-binaries` の Node.js 24.19.0 は、
eMudhra の侵害された中間 CA につながる証明書を受け入れ、PATH の修正版より優先されるためです。
依存は `uv sync --locked --all-groups` で同期し、既存環境に入っていた旧 wheel も取り除きます。
通常の検証には外部ホストへの TLS プローブを含めず、ネットワーク障害と証明書の拒否を混同しません。

背景: [Issue #13](https://github.com/usaturn/wabun-rst-ulint/issues/13)
