"""Secure docutils oracle adapter contracts (Issue #10)."""

from __future__ import annotations

import io
from contextlib import redirect_stderr

import docutils
import pytest

from wabun_rst_ulint.checkers import _rst_oracle as oracle


class TestOracleSecurity:
    def test_supported_docutils_version_line(self) -> None:
        version = oracle.require_supported_docutils()
        assert version.startswith("0.22")

    def test_default_settings_contract(self) -> None:
        s = oracle.default_settings()
        assert s["file_insertion_enabled"] is False
        assert s["raw_enabled"] is False
        assert s["report_level"] == 1
        assert s["halt_level"] == 5
        assert s["input_encoding"] == "unicode"
        assert isinstance(s["warning_stream"], io.StringIO)

    def test_warnings_do_not_leak_to_stderr(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            doc = oracle.parse_document("**broken\n")
        assert buf.getvalue() == ""
        # warnings captured on stream or tree
        assert doc.warning_stream is not None

    def test_opaque_role_kind_and_registry_restore(self) -> None:
        assert not oracle.role_registry_has("term")
        doc = oracle.parse_document("see :term:`X` here\n")
        kinds = [i.kind for i in doc.inlines]
        assert "opaque_role" in kinds
        assert not oracle.role_registry_has("term")

    def test_scoped_roles_no_cross_parse_leakage(self) -> None:
        oracle.parse_document(":ref:`a`\n")
        assert not oracle.role_registry_has("ref")
        oracle.parse_document("plain text\n")
        assert not oracle.role_registry_has("ref")

    def test_include_does_not_insert_files(self, tmp_path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("SECRET_PAYLOAD\n", encoding="utf-8")
        source = f".. include:: {secret}\n"
        doc = oracle.parse_document(source)
        text = doc.document.astext()
        assert "SECRET_PAYLOAD" not in text

    def test_parse_count_increments_once(self) -> None:
        ctr = oracle.OracleCounters()
        oracle.parse_document("値は ``foo`` です\n", counters=ctr)
        assert ctr.parse_count == 1

    def test_default_settings_disable_config_and_traceback(self) -> None:
        s = oracle.default_settings()
        assert s["_disable_config"] is True
        assert s["traceback"] is True

    def test_external_docutils_conf_cannot_override_secure_settings(self, tmp_path, monkeypatch) -> None:
        conf = tmp_path / "docutils.conf"
        conf.write_text(
            "[general]\nfile_insertion_enabled: yes\nraw_enabled: yes\nhalt_level: 2\n",
            encoding="utf-8",
        )
        secret = tmp_path / "secret.txt"
        secret.write_text("SECRET_PAYLOAD\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        doc = oracle.parse_document("普通の段落 ``x`` です\n")
        settings = doc.document.settings
        assert settings.file_insertion_enabled is False
        assert settings.raw_enabled is False
        assert settings.halt_level == 5

        doc2 = oracle.parse_document(".. include:: secret.txt\n")
        assert "SECRET_PAYLOAD" not in doc2.document.astext()

    def test_settings_overrides_cannot_reenable_include_or_raw(self, tmp_path, monkeypatch) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("SECRET_PAYLOAD\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        doc = oracle.parse_document(
            ".. include:: secret.txt\n",
            settings_overrides={
                "file_insertion_enabled": True,
                "raw_enabled": True,
                "input_encoding": "utf-8",
            },
        )
        assert doc.document.settings.file_insertion_enabled is False
        assert doc.document.settings.raw_enabled is False
        assert "SECRET_PAYLOAD" not in doc.document.astext()

    def test_parse_document_does_not_raise_systemexit(self, tmp_path, monkeypatch) -> None:
        """Even under hostile conf, parse must not sys.exit the host process."""
        conf = tmp_path / "docutils.conf"
        conf.write_text(
            "[general]\nfile_insertion_enabled: yes\nhalt_level: 2\n",
            encoding="utf-8",
        )
        (tmp_path / "secret.txt").write_text("SECRET_PAYLOAD\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        try:
            oracle.parse_document(".. include:: secret.txt\n")
        except SystemExit as exc:  # pragma: no cover - failure path
            raise AssertionError(f"SystemExit leaked from oracle: {exc}") from exc

    def test_uppercase_role_name_does_not_leak_registry(self) -> None:
        assert not oracle.role_registry_has("pep")
        assert not oracle.role_registry_has("rfc")
        oracle.parse_document("詳細は :PEP:`287` と :RFC:`2822` を参照\n")
        assert not oracle.role_registry_has("pep")
        assert not oracle.role_registry_has("rfc")
        assert not oracle.role_registry_has("PEP")
        assert not oracle.role_registry_has("RFC")

    def test_mixed_case_same_role_restores_once(self) -> None:
        oracle.parse_document("A :Term:`X` and :term:`Y`\n")
        assert not oracle.role_registry_has("term")
        assert not oracle.role_registry_has("Term")


class TestPhysicalMapping:
    def test_order_preserving_repeated_rawsource(self) -> None:
        source = "a ``x`` b ``x`` c\n"
        doc = oracle.parse_document(source)
        aligned = oracle.align_inlines_to_source(source, doc.inlines)
        literals = [a for a in aligned if a.kind == "literal"]
        assert len(literals) >= 2
        assert literals[0].start < literals[1].start
        assert source[literals[0].start : literals[0].end] == "``x``"
        assert source[literals[1].start : literals[1].end] == "``x``"

    def test_no_arbitrary_nearest_from_start_after_miss(self) -> None:
        # Empty rawsource cannot be aligned; subsequent items must not jump
        fake = (
            oracle.OracleInline(kind="literal", rawsource="", visible_text="", line=1),
            oracle.OracleInline(kind="literal", rawsource="``x``", visible_text="x", line=1),
        )
        aligned = oracle.align_inlines_to_source("``x``\n", fake)
        assert aligned == []

    def test_line_column_one_based(self) -> None:
        source = "line1\n値は ``foo`` です\n"
        doc = oracle.parse_document(source)
        aligned = oracle.align_inlines_to_source(source, doc.inlines)
        assert aligned
        lit = next(a for a in aligned if a.kind == "literal")
        assert lit.line == 2
        assert lit.column >= 1
        line, col = oracle.offset_to_line_column(source, lit.start)
        assert line == lit.line and col == lit.column

    def test_offset_to_line_column_matches_with_newline_index(self) -> None:
        source = "a\nbb\nccc\n"
        newlines = oracle.newline_offsets(source)
        for offset in range(len(source) + 1):
            assert oracle.offset_to_line_column(source, offset) == oracle.offset_to_line_column(
                source, offset, newlines=newlines
            )

    def test_opaque_role_aligns(self) -> None:
        source = "用語 :term:`SCIM` 同期\n"
        doc = oracle.parse_document(source)
        aligned = oracle.align_inlines_to_source(source, doc.inlines)
        roles = [a for a in aligned if a.kind == "opaque_role"]
        assert roles
        assert source[roles[0].start : roles[0].end] == roles[0].rawsource


class TestOracleAuthority:
    def test_note_body_is_not_opaque_range(self) -> None:
        source = ".. note::\n\n   値は``x``です\n"
        opaque = oracle.opaque_body_ranges(source)
        # body text position of ``x``
        idx = source.index("``x``")
        assert not oracle.range_in_opaque(idx, idx + 5, opaque)

    def test_unknown_directive_body_opaque(self) -> None:
        source = ".. unknown-directive::\n\n   body ``x`` y\n"
        opaque = oracle.opaque_body_ranges(source)
        idx = source.index("``x``")
        assert oracle.range_in_opaque(idx, idx + 5, opaque)

    def test_raw_directive_body_opaque(self) -> None:
        source = ".. raw:: html\n\n   <b>``x``</b>\n"
        opaque = oracle.opaque_body_ranges(source)
        idx = source.index("``x``")
        assert oracle.range_in_opaque(idx, idx + 5, opaque)

    def test_range_in_opaque_start_inside_not_mere_overlap(self) -> None:
        source = ".. unknown-directive::\n\n   body ``x`` y\n"
        opaque = oracle.opaque_body_ranges(source)
        idx = source.index("``x``")
        assert oracle.range_in_opaque(idx, idx + 5, opaque) is True
        # Overlap from before body into body should be False under start-inside rule
        if opaque:
            o0, o1 = opaque[0]
            if o0 > 0:
                assert oracle.range_in_opaque(o0 - 1, o0 + 1, opaque) is False

    def test_substitution_multiline_body_not_opaque(self) -> None:
        source = ".. |m| replace::\n   値は``x``です\n"
        assert oracle.opaque_body_ranges(source) == []

    def test_footnote_multiline_body_not_opaque(self) -> None:
        source = ".. [1]\n   値は``x``です\n"
        assert oracle.opaque_body_ranges(source) == []

    def test_citation_multiline_body_not_opaque(self) -> None:
        source = ".. [CIT2020]\n   値は``x``です\n"
        assert oracle.opaque_body_ranges(source) == []

    def test_plain_comment_body_stays_opaque(self) -> None:
        source = ".. ただのコメント\n   値は``x``です\n"
        opaque = oracle.opaque_body_ranges(source)
        assert opaque, "comment body must remain opaque"
        idx = source.index("``x``")
        assert oracle.range_in_opaque(idx, idx + 5, opaque) is True

    def test_extract_skips_inlines_inside_literal_block(self) -> None:
        source = "not here\n\n.. code:: python\n\n   not = 1\n\n``yes``\n"
        doc = oracle.parse_document(source)
        raws = [i.rawsource for i in doc.inlines]
        assert "not" not in raws
        assert "=" not in raws
        assert "1" not in raws
        assert any(i.kind == "literal" and i.rawsource == "``yes``" for i in doc.inlines)

    def test_extract_skips_strong_inside_parsed_literal(self) -> None:
        source = "intro\n\n.. parsed-literal::\n\n   **bold** here\n\nout **ok**\n"
        doc = oracle.parse_document(source)
        strong_raws = [i.rawsource for i in doc.inlines if i.kind == "strong"]
        assert strong_raws == ["**ok**"]


class TestVersionGuard:
    def test_reject_non_022_minor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(docutils, "__version__", "0.21.2")
        with pytest.raises(oracle.OracleVersionError, match="0.22"):
            oracle.require_supported_docutils()


class TestAlignmentStatus:
    def test_align_with_status_reports_truncation_line(self) -> None:
        source = "冒頭 ``head`` です。\n\n- 項目 **重要\n  箇所** です\n\n続き ``bar`` です。\n"
        doc = oracle.parse_document(source)
        aligned, truncated = oracle.align_inlines_with_status(source, doc.inlines)
        assert [a.rawsource for a in aligned] == ["``head``"]
        assert truncated == 1

    def test_align_with_status_reports_none_when_complete(self) -> None:
        source = "本文 ``x`` と ``y`` です\n"
        doc = oracle.parse_document(source)
        aligned, truncated = oracle.align_inlines_with_status(source, doc.inlines)
        assert truncated is None
        assert [a.rawsource for a in aligned] == ["``x``", "``y``"]
