===============
wabun-rst-ulint
===============

reStructuredText ドキュメントの検査・修正 CLI ツール

インストール
============

動作には Python 3.14 以上と docutils 0.22 以上 0.23 未満が必要である。
uv でセットアップする ::

   uv sync

基本的な使い方
==============

全サブコマンドに共通する呼び出しパターンは以下のとおりである ::

   uv run wabun-rst-ulint <subcommand> [--check|--fix] <paths...>

``paths`` にはファイルまたはディレクトリを指定する。
ディレクトリを指定した場合は ``.rst`` ファイルを再帰的に検索する

``--check`` と ``--fix`` は相互排他のオプションである。
``--check`` は違反の検出のみを行い、違反があれば終了コード 1 で終了する。
``--fix`` は検出された違反を自動修正する。
どちらも指定しない場合は ``--check`` と同じ動作になる

サブコマンド
============

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - サブコマンド
     - 検査対象
   * - ``inline-spacing``
     - インライン記法の外部境界スペース
   * - ``strong-spacing``
     - 強調表示前後の半角スペース
   * - ``heading-width``
     - セクションタイトル装飾行の表示幅
   * - ``sentence-breaks``
     - 句点と改行のスタイルルール

inline-spacing
--------------

インライン記法（インラインリテラル、role 参照、名前付き参照、匿名参照、内部ターゲット、
interpreted text）の外部境界にある半角スペースの過不足を検出・修正する

対象となる根拠は 2 種類ある

1. **認識の修復** — 日本語文字に直接隣接するインライン記法は docutils が正しく認識できず、
   markup が黙って通常のテキストとして描画される
2. **和文の視認性** — docutils が正しく認識する場合でも、和文組版として境界を分離するために
   半角スペースを補う。
   CJK 句読点の直前、中黒の前後、隣接する role の間がこれにあたる

それぞれの例を示す（左が入力、右が ``--fix`` の出力）::

   1. 認識の修復
      値は``foo``です          →  値は ``foo`` です

   2. 和文の視認性
      これは :term:`X`。       →  これは :term:`X` 。
      中黒・:term:`X`・区切り  →  中黒・ :term:`X` ・区切り
      :ref:`a`:ref:`b` です    →  :ref:`a` :ref:`b` です

2 の適用範囲は Issue #22 で確定した。
旧 ``role_visible_spacing`` は 2 を適用し、旧 ``role_spacing`` と旧 ``inline_markup`` は
同じ構文を無変更としていたため、1 つの classifier へ統合した時点で衝突していた。
``inline-spacing`` は 2 を採用する ::

   uv run wabun-rst-ulint inline-spacing docs/
   uv run wabun-rst-ulint inline-spacing --fix docs/

strong-spacing
--------------

強調表示の前後に半角スペースがない箇所を検出・修正する。
二重アスタリスクの strong emphasis （ ``**...**`` ）のみを対象とし、
単一アスタリスクの emphasis （ ``*...*`` ）は対象外である ::

   uv run wabun-rst-ulint strong-spacing --fix source/

heading-width
-------------

セクションタイトルの下線・上下線の表示幅がタイトルと一致しない場合を検出・修正する。
日本語全角文字は表示幅 2 として計算する

共通オプションに加え、以下の追加オプションを持つ

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - オプション
     - 説明
   * - ``--diff``
     - 修正案を unified diff 形式で標準エラー出力に表示する（ファイルは書き換えない）。
       ``--check`` / ``--fix`` と相互排他
   * - ``--backup-suffix SUFFIX``
     - ``--fix`` の前に元ファイルのバックアップを作成する。
       ``--fix`` との併用が必須。空文字列、パスセパレータ、 ``..`` は指定できない
   * - ``--follow-symlinks``
     - シンボリックリンクを検査対象に含める（既定ではスキップ）。
       ``--fix`` とは併用不可

使用例 ::

   uv run wabun-rst-ulint heading-width --diff docs/
   uv run wabun-rst-ulint heading-width --fix --backup-suffix .bak docs/

sentence-breaks
---------------

句点と改行に関するスタイルルールを検出・修正する。
本文中の句点の後ろで改行されていない箇所、およびテキストブロック末尾の不要な句点を検出する

追加オプションとして ``--follow-symlinks`` を持つ。
I/O エラーが発生した場合は終了コード 2 を返す（他のサブコマンドは終了コード 1） ::

   uv run wabun-rst-ulint sentence-breaks --fix docs/

Issue #14 での破壊的変更
========================

以下の 6 コマンドは削除された。エイリアスおよび非推奨警告は提供しないため、
旧コマンド名を指定した場合は終了コード 2 で拒否される

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 旧コマンド
     - 移行先
   * - ``literal-spacing``
     - ``inline-spacing`` に統合
   * - ``role-spacing``
     - ``inline-spacing`` に統合
   * - ``role-visible-spacing``
     - ``inline-spacing`` に統合
   * - ``inline-markup``
     - ``inline-spacing`` に統合
   * - ``section-underline``
     - ``heading-width`` に改称
   * - ``kuten``
     - ``sentence-breaks`` に改称

ディレクトリの再帰検索
======================

サブコマンドによりディレクトリの再帰検索の動作が異なる

``heading-width`` と ``sentence-breaks`` は管理用ディレクトリ（ ``.git`` 、 ``.venv`` 、 ``__pycache__`` 、 ``node_modules`` 、 ``_build`` 等）を自動的に除外する。
シンボリックリンクは ``--follow-symlinks`` を指定した場合のみ検査対象に含める

``inline-spacing`` と ``strong-spacing`` はディレクトリの除外を行わず、シンボリックリンクの制御オプションも持たない

.. warning::

   ``inline-spacing`` と ``strong-spacing`` は管理用ディレクトリを除外しないため、
   リポジトリ直下で ``--fix .`` を実行すると ``.venv`` や ``node_modules`` 配下の
   ``.rst`` ファイルも書き換える。これらのコマンドで ``--fix`` を使う場合は
   ``.`` ではなく対象ディレクトリを明示的に指定すること

出力先
======

``sentence-breaks`` は検出結果を標準出力に書き込む。
それ以外の 3 コマンド（ ``inline-spacing`` 、 ``strong-spacing`` 、 ``heading-width`` ）は
検出結果（ ``heading-width`` の ``--diff`` 出力を含む）を標準エラー出力に書き込む。
標準出力のみをリダイレクトしても、この 3 コマンドの結果は捕捉できない

終了コード
==========

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - コード
     - 意味
   * - 0
     - 違反なし、または ``--fix`` による修正が成功
   * - 1
     - 違反を検出、対象ファイルが見つからない、読み取り/書き込みエラー
   * - 2
     - 引数エラー（全サブコマンド。未知のコマンド名や排他オプションの同時指定など argparse が拒否した場合）、
       および ``sentence-breaks`` の I/O エラー

開発
====

テストを実行する ::

   uv run pytest

lint を実行する ::

   uv run task ruff

Release gate
------------

inline replacement の release gate は、seed ``1507`` で固定した42件
（pairwise 32件、interaction 10件）の generated cases と、frozen full corpus を検証する。
generated cases は42件それぞれについて、凍結した期待出力（または no-write）と一致することを検査する。
frozen full corpus は127件（うち must_fix 57件）で、件数と must_fix 件数、および57件の
owner command 出力はこの127件に対して検査する。CLI をツリー単位で実行する gate は、
transaction 失敗を注入する fixture 1件を意図的に除いた126件を materialize する。
CI は Python 3.14 上で imported ``docutils==0.22.4`` を明示的に確認する。

隣接する interpreted text / role / reference と inline literal は、1回の
``inline-spacing --fix`` ですべての候補を修正しない場合がある。運用では推奨順
``sentence-breaks -> inline-spacing -> strong-spacing -> heading-width`` を最大3巡し、
3巡目に変更がないことを確認する。release gate は、frozen full corpus が1巡目で
fixed point に到達すること、および隣接ケースを含む代表ドキュメントが2巡目までに到達して
3巡目が no-op になることを検証する。

ローカルで CI と同じ gate を実行する ::

   uv run --isolated --with 'docutils==0.22.4' --with 'pytest>=8' python -c 'import docutils; assert docutils.__version__ == "0.22.4"'
   uv run --isolated --with 'docutils==0.22.4' --with 'pytest>=8' pytest -q
   uvx ruff check src tests
   uvx ruff format --check src tests
   git diff --check origin/main...HEAD

空白エラーの検査は range 形式で実行する。checkout 直後の working tree は clean なので、
引数なしの ``git diff --check`` では何も検査できない。CI は ``pull_request`` イベントで
PR base との merge-base 比較を実行し、PR が追加した行だけを検査する。
