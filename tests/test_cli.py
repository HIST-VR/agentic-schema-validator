import pytest

from extraction_engine.__main__ import main


def test_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0


def test_requires_exactly_one_source() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--schema", "invoice"])
    assert caught.value.code == 2


def test_empty_text_fails_before_any_provider_call(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--schema", "invoice", "--text", "   "])
    captured = capsys.readouterr()
    assert code == 1
    assert "empty" in captured.err.lower()
    assert captured.out == ""
