===============
wabun-rst-ulint
===============

reStructuredText ドキュメントの検査・修正 CLI ツール

Important Notes 注意事項
========================

The default rules are designed for Japanese text.
For documents in other languages, check the boundaries of inline markup with ``inline-spacing --syntax-only``.

既定の規則は日本語の文書向けである。
日本語以外の文書では、インライン記法の境界を ``inline-spacing --syntax-only`` で検査する

機能紹介
========

- インライン記法の前後スペースを検査・修正する
- 日本語以外の文書向けに、docutils が認識できないインライン記法の境界を検査する（ ``inline-spacing --syntax-only`` ）
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
既定の規則は日本語の文書向けである。
日本語に直接隣接すると docutils が markup を認識できない。
role 参照、名前付き参照、匿名参照、内部ターゲット、interpreted text には、docutils が認識できる場合でも、句読点の直前、中黒の前後、隣接する role の間に半角スペースを補う。
インラインリテラルは、 ``。`` ``、`` や ASCII の句読点、括弧・引用符とは、スペースなしで接してよい ::

   値は``foo``です          →  値は ``foo`` です
   値は ``foo``。           →  変更しない
   これは :term:`X`。       →  これは :term:`X` 。
   中黒・:term:`X`・区切り  →  中黒・ :term:`X` ・区切り
   :ref:`a`:ref:`b` です    →  :ref:`a` :ref:`b` です

   wabun-rst-ulint inline-spacing docs/
   wabun-rst-ulint inline-spacing --fix docs/

インラインリテラルと role などで扱いが異なるのは、role などの句読点・中黒・隣接する role の規則を、和文の見やすさを優先して採用したためである。
docutils はこれらの境界も認識するので、この規則は構文の誤りではなく表記を揃えるためのものである。
インラインリテラルには、この規則を適用していない

--syntax-only
~~~~~~~~~~~~~

日本語以外の文書（英文など）向けのオプションである。
``--check`` 、 ``--fix`` のどちらとも組み合わせられる。
指定しなければ既定の規則で検査する

docutils がインライン記法の境界として認識できない箇所だけを違反にする。
判定は docutils と同じく、開始記号の前と終了記号の後の文字で行う

- 開始記号の前は、行頭、空白、開き括弧・引用符、 ``-`` ``/`` ``:`` などの区切り記号なら認識される。
  直前がほかのインライン記法の終わりの場合も認識される
- 終了記号の後は、行末、空白、閉じ括弧・引用符、句読点、バックスラッシュ、 ``-`` ``/`` ``:`` などの区切り記号なら認識される

文字の分類は docutils の ``docutils.utils.punctuation_chars`` に従う。
null escape（バックスラッシュの直後に半角スペース）、NBSP、タブ、全角空白も境界として認識されるので変えない

``--fix`` は、開始記号の前が文字・数字の場合だけ半角スペースを入れる。
ほかの違反は検出だけで、書き換えない。
終了記号の後に文字が続く場合は、スペースの書き忘れか接尾辞（ ``queue`` に s を続けた複数形など）かを区別できないためである。
記号と接する場合は、正しい直し方がスペースのことも null escape のこともある。
``--fix`` の後も違反が残った場合は、その違反を表示して終了コード 1 で終了する ::

   the:ref:`roles` page        →  the :ref:`roles` page
   see :ref:`roles`page now    →  検出だけ
   set FOO=``bar`` now         →  検出だけ
   (:ref:`roles`), :ref:`roles`'s, ``queue``\ s  →  違反にしない

   wabun-rst-ulint inline-spacing --syntax-only docs/
   wabun-rst-ulint inline-spacing --fix --syntax-only docs/

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
     - 違反を検出、 ``inline-spacing --fix --syntax-only`` の後も違反が残った、対象ファイルが見つからない、読み取り/書き込みエラー
   * - 2
     - 引数エラー。 ``sentence-breaks`` の I/O エラーも 2
