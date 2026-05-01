# -*- coding: utf-8 -*-
"""
出力CSVのバイトレベルフォーマット検証。

GX Works3が読み込める条件:
  - UTF-16 LE + BOM (FF FE)
  - タブ区切り
  - 行末 CRLF
  - 各セルが `"..."` 囲み
  - 1～8行目はヘッダー、9行目はカラム見出し（29カラム）、10行目以降が設定データ
"""

from __future__ import annotations

import codecs
from pathlib import Path

import pytest

import generate_csv as gc

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

ALL_FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))


def _decode_utf16le(raw: bytes) -> str:
    assert raw.startswith(codecs.BOM_UTF16_LE), "UTF-16 LE BOMで始まること"
    return raw[2:].decode("utf-16-le")


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_bom_is_utf16le(fx, tmp_path):
    """先頭バイトはUTF-16LE BOM (FF FE) であること。"""
    out = tmp_path / f"{fx.stem}.csv"
    config = _load_json(fx)
    gc.generate_csv(config, out)
    raw = out.read_bytes()
    assert raw[:2] == codecs.BOM_UTF16_LE


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_line_separator_is_crlf(fx, tmp_path):
    """行区切りはCRLFであること（LFのみ／CRのみは禁止）。"""
    out = tmp_path / f"{fx.stem}.csv"
    config = _load_json(fx)
    gc.generate_csv(config, out)
    text = _decode_utf16le(out.read_bytes())
    # CRLFで分割した後、各行に \n も \r も単独で残らないこと
    for line in text.split("\r\n"):
        assert "\r" not in line and "\n" not in line


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_field_separator_is_tab(fx, tmp_path):
    """フィールド区切りはタブ。カンマは区切りとして使われていない。"""
    out = tmp_path / f"{fx.stem}.csv"
    config = _load_json(fx)
    gc.generate_csv(config, out)
    text = _decode_utf16le(out.read_bytes())
    # 9行目（カラム見出し）にタブが28個（29カラム）あること
    lines = [ln for ln in text.split("\r\n") if ln]
    assert lines[8].count("\t") == 28


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_all_cells_quoted(fx, tmp_path):
    """全セルが `"..."` で囲まれていること。"""
    out = tmp_path / f"{fx.stem}.csv"
    config = _load_json(fx)
    gc.generate_csv(config, out)
    text = _decode_utf16le(out.read_bytes())
    for i, line in enumerate(text.split("\r\n")):
        if line == "":
            continue
        # 最初と最後の文字が " であること
        assert line.startswith('"'), f"行{i+1}: 先頭が \" でない: {line!r}"
        assert line.endswith('"'), f"行{i+1}: 末尾が \" でない: {line!r}"


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_header_row_count_and_keys(fx, tmp_path):
    """1～8行目のヘッダーキーが仕様通りで、9行目はカラム見出しであること。"""
    out = tmp_path / f"{fx.stem}.csv"
    config = _load_json(fx)
    gc.generate_csv(config, out)
    text = _decode_utf16le(out.read_bytes())
    lines = text.split("\r\n")

    # 行1: ファイルバージョン
    assert _split(lines[0])[0] == "ファイルバージョン"
    # 行2: 単一フィールド (タイトル)
    assert _split(lines[1]) == [str(config.get("header", {}).get("title", ""))]
    # 行3: 対象ユニット
    assert _split(lines[2])[0] == "対象ユニット"
    # 行4: 自局IPアドレス
    assert _split(lines[3])[0] == "自局IPアドレス"
    # 行5: IPアドレス入力形式
    assert _split(lines[4])[0] == "IPアドレス入力形式"
    # 行6: デバイス割付方法
    assert _split(lines[5])[0] == "デバイス割付方法"
    # 行7: 通信開始待ち時間
    assert _split(lines[6])[0] == "通信開始待ち時間"
    # 行8: 初回交信設定
    assert _split(lines[7])[0] == "初回交信設定"
    # 行9: カラム見出し（29カラム）
    cols9 = _split(lines[8])
    assert len(cols9) == 29
    assert cols9 == gc.COLUMN_HEADERS


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_data_rows_have_29_columns(fx, tmp_path):
    """10行目以降の設定データはすべて29カラムあること。"""
    out = tmp_path / f"{fx.stem}.csv"
    config = _load_json(fx)
    gc.generate_csv(config, out)
    text = _decode_utf16le(out.read_bytes())
    lines = [ln for ln in text.split("\r\n") if ln]
    for i, line in enumerate(lines[9:], start=10):
        cols = _split(line)
        assert len(cols) == 29, f"行{i}: カラム数={len(cols)}（期待値29）"


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_setting_count_matches_config(fx, tmp_path):
    """設定行数 == JSON設定の settings 件数。"""
    out = tmp_path / f"{fx.stem}.csv"
    config = _load_json(fx)
    gc.generate_csv(config, out)
    text = _decode_utf16le(out.read_bytes())
    lines = [ln for ln in text.split("\r\n") if ln]
    data_rows = lines[9:]
    assert len(data_rows) == len(config["settings"])


def test_committed_samples_match_regen(tmp_path):
    """samples/ 配下の既存CSVが、現状のgenerate_csv.pyで再生成しても同一バイトになること。

    fixture を変更したら samples もコミットし直すこと。
    """
    for fx in ALL_FIXTURES:
        sample_path = SAMPLES_DIR / f"{fx.stem}.csv"
        if not sample_path.exists():
            continue
        regen = tmp_path / f"{fx.stem}.csv"
        gc.generate_csv(_load_json(fx), regen)
        assert regen.read_bytes() == sample_path.read_bytes(), \
            f"{fx.stem}: 既存サンプルと再生成結果が不一致"


# ----- ヘルパ -----


def _load_json(p: Path) -> dict:
    import json
    return json.loads(p.read_text(encoding="utf-8"))


def _split(line: str) -> list[str]:
    """CSV1行を `"..."` セルに分解。"""
    out, i, n = [], 0, len(line)
    cur, in_q = "", False
    while i < n:
        ch = line[i]
        if ch == '"':
            if in_q and i + 1 < n and line[i + 1] == '"':
                cur += '"'
                i += 2
                continue
            in_q = not in_q
            i += 1
            continue
        if ch == "\t" and not in_q:
            out.append(cur)
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    out.append(cur)
    return out
