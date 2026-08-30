===============
wabun-rst-ulint
===============

reStructuredText ドキュメントの検査・修正 CLI ツール

Important Notes 注意事項
========================

This utility is intended for Japanese text and does not work with other languages.

このユーティリティは日本語向けであり、他の言語では使えない

機能紹介
========

- インライン記法の前後スペースを検査・修正する
- 強調表示（ ``**...**`` ）の前後スペースを検査・修正する
- セクションタイトルの下線幅を検査・修正する
- 句点と改行のスタイルを検査・修正する（注意: 末尾の句点を削除する特殊なスタイルである）

インストール
============

Python 3.14 以上が必要である。
PyPI からパッケージを入れると、依存の docutils 0.22 系も同時に入る

uv で CLI としてインストールする ::

   uv tool install wabun-rst-ulint

pip でインストールする ::

   pip install wabun-rst-ulint

インストール後は ``wabun-rst-ulint`` コマンドが使える。
次で確認する ::

   wabun-rst-ulint --help

使い方
======

呼び出しは次のとおりである ::

   wabun-rst-ulint <subcommand> [--check|--fix] <paths...>

``paths`` にはファイルまたはディレクトリを指定する。
ディレクトリを指定した場合は ``.rst`` ファイルを再帰的に検索する

``--check`` と ``--fix`` は相互排他である。
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

インライン記法（インラインリテラル、role 参照、名前付き参照、匿名参照、内部ターゲット、interpreted text）の外部境界にある半角スペースの過不足を検出・修正する。
日本語に直接隣接すると docutils が markup を認識できない。
認識できる場合でも、句読点の直前、中黒の前後、隣接する role の間には半角スペースを補う ::

   値は``foo``です          →  値は ``foo`` です
   これは :term:`X`。       →  これは :term:`X` 。
   中黒・:term:`X`・区切り  →  中黒・ :term:`X` ・区切り
   :ref:`a`:ref:`b` です    →  :ref:`a` :ref:`b` です

   wabun-rst-ulint inline-spacing docs/
   wabun-rst-ulint inline-spacing --fix docs/

strong-spacing
--------------

強調表示 ``**...**`` の前後に半角スペースがない箇所を検出・修正する。
単一アスタリスクの emphasis （ ``*...*`` ）は対象外である ::

   wabun-rst-ulint strong-spacing --fix source/

heading-width
-------------

セクションタイトルの下線・上下線の表示幅がタイトルと一致しない場合を検出・修正する。
日本語全角文字は表示幅 2 として計算する

追加オプションは次のとおりである

- ``--diff`` : 修正案を unified diff として標準エラー出力に出す。
  ファイルは書き換えない。
  ``--check`` / ``--fix`` と相互排他
- ``--backup-suffix SUFFIX`` : ``--fix`` の前にバックアップを作る。
  ``--fix`` との併用が必須
- ``--follow-symlinks`` : シンボリックリンクを検査対象に含める。
  ``--fix`` とは併用できない ::

   wabun-rst-ulint heading-width --diff docs/
   wabun-rst-ulint heading-width --fix --backup-suffix .bak docs/

sentence-breaks
---------------

本文中の句点の後ろで改行されていない箇所と、テキストブロック末尾の不要な句点を検出・修正する。
``--follow-symlinks`` を持つ ::

   wabun-rst-ulint sentence-breaks --fix docs/

ディレクトリの再帰検索
======================

``heading-width`` と ``sentence-breaks`` は ``.git`` 、 ``.venv`` 、 ``__pycache__`` 、 ``node_modules`` 、 ``_build`` などを除外する。
シンボリックリンクは ``--follow-symlinks`` を付けたときだけ対象に含める

``inline-spacing`` と ``strong-spacing`` はディレクトリを除外しない。
これらの ``--fix`` では ``.`` ではなく対象ディレクトリを明示する

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
     - 引数エラー。 ``sentence-breaks`` の I/O エラーも 2
