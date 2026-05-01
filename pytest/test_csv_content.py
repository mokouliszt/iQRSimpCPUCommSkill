# -*- coding: utf-8 -*-
"""
出力CSVのセル単位の内容検証。

- 機器種別コードが正しい数値で書かれている
- iQ-R/iQ-L の X/Y は16進5桁ゼロパディング
- iQ-F の X/Y は8進パディングなし
- request 時は interval / error_monitor_sec が空セル
- iQ-R(16) は port/local_port が空セル
- A/AnS(25) / SLMP(30) は port/local_port が値入り
- iQ-Rプロジェクトは IPアドレス入力形式=DEC 固定（HEXは GX Works3 が行を破棄するため不可）
- iQ-Rプロジェクトは オプション(16進数) 空欄固定（GUI で変更不可、値があると行が破棄される）
"""

from __future__ import annotations

import codecs
import json
from pathlib import Path

import pytest

import generate_csv as gc

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _split(line: str) -> list[str]:
    """`"..."` セル分解（test_csv_format.py と同じ）。"""
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


def _gen_and_split(fx: Path, tmp_path: Path) -> tuple[dict, list[list[str]]]:
    """fixtureからCSV生成し、データ行（10行目以降）を返す。"""
    cfg = json.loads(fx.read_text(encoding="utf-8"))
    out = tmp_path / f"{fx.stem}.csv"
    gc.generate_csv(cfg, out)
    raw = out.read_bytes()
    text = raw[2:].decode("utf-16-le")
    lines = [ln for ln in text.split("\r\n") if ln]
    data_rows = [_split(ln) for ln in lines[9:]]
    return cfg, data_rows


# ---- 個別 fixture の中身を検証する一連のテスト ----


def test_01_basic_iqr_first_row(tmp_path):
    """01_basic_iqr: Read X 16ビット, periodic 100ms, iQ-R(16), port空。"""
    fx = FIXTURES_DIR / "01_basic_iqr.json"
    _, rows = _gen_and_split(fx, tmp_path)
    r = rows[0]
    # 設定No.
    assert r[0] == "1"
    # 通信パターン
    assert r[1] == "Read"
    # 交信設定 1=periodic
    assert r[2] == "1"
    # 実行間隔
    assert r[3] == "100"
    # 機器種別 16
    assert r[4] == "16"
    # IP DEC表記
    assert r[5] == "127.0.0.1"
    # TCP/UDP
    assert r[6] == "UDP"
    # iQ-R は port/local_port 空
    assert r[7] == ""
    assert r[8] == ""
    # ビット点数
    assert r[11] == "16"
    # iQ-R Xは16進5桁ゼロパディング
    assert r[12] == "X"
    assert r[13] == "00000"
    assert r[14] == "0000F"
    # 自局側も同様
    assert r[15] == "X"
    assert r[16] == "00000"
    assert r[17] == "0000F"
    # ワードデバイスは空
    for i in range(18, 25):
        assert r[i] == ""
    # 通信タイムアウト・リトライ・異常監視
    assert r[25] == "1000"
    assert r[26] == "3"
    assert r[27] == "30"
    # コメント
    assert r[28] == "テスト"


def test_01_basic_iqr_request_row(tmp_path):
    """01_basic_iqr: 設定2は request、interval/error_monitor_sec が空。"""
    fx = FIXTURES_DIR / "01_basic_iqr.json"
    _, rows = _gen_and_split(fx, tmp_path)
    r = rows[1]
    assert r[0] == "2"
    assert r[1] == "Write"
    assert r[2] == "0"  # request
    assert r[3] == ""   # interval空
    assert r[27] == ""  # error_monitor_sec空（request時）


def test_02_iqf_octal_xy_octal(tmp_path):
    """02_iqf_octal: iQ-F の X/Y は base 8 (octal) で書かれる。"""
    fx = FIXTURES_DIR / "02_iqf_octal.json"
    _, rows = _gen_and_split(fx, tmp_path)
    # 設定1: src=X 0-37 (8進), dst=M 0-31
    r1 = rows[0]
    assert r1[4] == "19"  # iQ-F
    assert r1[12] == "X"
    assert r1[13] == "0"
    assert r1[14] == "37"  # 8進 37 = 10進 31
    assert r1[15] == "M"
    assert r1[16] == "0"
    assert r1[17] == "31"
    # 設定2: src=Y 自局(iQ-R 16進5桁) / dst=Y 相手(iQ-F 8進)
    r2 = rows[1]
    assert r2[12] == "Y"
    assert r2[13] == "00000"  # 自局iQ-R Y は5桁hex
    assert r2[14] == "0000F"
    assert r2[15] == "Y"
    assert r2[16] == "0"      # 相手iQ-F Y は8進
    assert r2[17] == "17"     # 8進17 = 10進15


def test_03_slmp_ports_present(tmp_path):
    """03_slmp_with_ports: SLMP(30) なので port/local_port に値あり。option_hex は常に空。"""
    fx = FIXTURES_DIR / "03_slmp_with_ports.json"
    _, rows = _gen_and_split(fx, tmp_path)
    r1 = rows[0]
    assert r1[4] == "30"
    assert r1[7] == "4999"  # port (SLMP の port は [1-4999]/[5010-65534])
    assert r1[8] == "6000"  # local_port
    assert r1[9] == ""      # option_hex は iQ-R では常に空欄
    r2 = rows[1]
    assert r2[7] == "5010"
    assert r2[8] == "6001"
    assert r2[9] == ""


def test_04_aans_d_extra_range(tmp_path):
    """04_aans_extra_range: A/AnS の D 9000-9009 範囲。"""
    fx = FIXTURES_DIR / "04_aans_extra_range.json"
    _, rows = _gen_and_split(fx, tmp_path)
    # 設定2: write D9000-9009
    r2 = rows[1]
    assert r2[4] == "25"
    assert r2[19] == "D"
    assert r2[20] == "0"
    assert r2[21] == "9"
    assert r2[22] == "D"
    assert r2[23] == "9000"
    assert r2[24] == "9009"


def test_05_dec_ip_format(tmp_path):
    """05_mixed_bit_word: ip_format=DEC（iQ-Rプロジェクトの固定値）。IP はドット表記。"""
    fx = FIXTURES_DIR / "05_mixed_bit_word.json"
    cfg, rows = _gen_and_split(fx, tmp_path)
    r = rows[0]
    assert r[5] == "192.168.3.40"


def test_05_mixed_bit_and_word_in_one_row(tmp_path):
    """05_mixed_bit_word: 1設定にビット256+ワード100が両方記述される。"""
    fx = FIXTURES_DIR / "05_mixed_bit_word.json"
    _, rows = _gen_and_split(fx, tmp_path)
    r = rows[0]
    assert r[11] == "256"  # bit points
    assert r[12] == "M"
    assert r[18] == "100"  # word points
    assert r[19] == "D"


def test_06_q_l_ports_blank(tmp_path):
    """06_q_l_ports_forbidden: Q(17) / L(18) / Q-EU(22) は port/local_port すべて空。"""
    fx = FIXTURES_DIR / "06_q_l_ports_forbidden.json"
    _, rows = _gen_and_split(fx, tmp_path)
    for r in rows:
        assert r[4] in ("17", "18", "22")
        assert r[7] == ""
        assert r[8] == ""


def test_06_l_ts_partner_read(tmp_path):
    """06: L(18) で TS を相手側から読出す例（pattern=Read, src=TS）。"""
    fx = FIXTURES_DIR / "06_q_l_ports_forbidden.json"
    _, rows = _gen_and_split(fx, tmp_path)
    r2 = rows[1]
    assert r2[1] == "Read"
    assert r2[4] == "18"  # L
    assert r2[12] == "TS"
    assert r2[13] == "0"
    assert r2[14] == "15"


def test_07_minimal_defaults_applied(tmp_path):
    """07_minimal_defaults: デフォルト値（timeout=1000, retry=3, error_mon=30）が設定される。"""
    fx = FIXTURES_DIR / "07_minimal_defaults.json"
    _, rows = _gen_and_split(fx, tmp_path)
    r = rows[0]
    assert r[6] == "UDP"
    assert r[10] == "0"   # cpu_no デフォルト
    assert r[25] == "1000"
    assert r[26] == "3"
    assert r[27] == "30"
    assert r[28] == ""    # comment デフォルト


def test_08_redundancy_distinct_local_ports(tmp_path):
    """08_redundancy_pair: 同一相手IPに対し設定1と設定2で local_port が異なる。"""
    fx = FIXTURES_DIR / "08_redundancy_pair.json"
    _, rows = _gen_and_split(fx, tmp_path)
    assert rows[0][5] == rows[1][5]  # 相手IP同じ
    assert rows[0][8] != rows[1][8]  # local_port異なる
    assert rows[0][8] == "1500"
    assert rows[1][8] == "1501"
