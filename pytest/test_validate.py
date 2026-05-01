# -*- coding: utf-8 -*-
"""
validate_config の検証規則テスト。

正常系（fixtures/）に加え、異常系を個別に与えて期待エラーが出ることを確認する。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import generate_csv as gc

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
ALL_FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))


# ============================================================
# 正常系: 全 fixture が検証OKであること
# ============================================================


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_all_fixtures_validate_clean(fx):
    """fixtures配下のJSONはエラーなしで検証通ること。"""
    import json
    cfg = json.loads(fx.read_text(encoding="utf-8"))
    errors = gc.validate_config(cfg)
    assert errors == [], f"{fx.stem}: 想定外エラー {errors}"


# ============================================================
# 異常系: 一つずつ規則違反を入れて、対応するエラーが出ることを確認
# ============================================================


@pytest.fixture
def base_config():
    """validate_config の異常系テスト用の最小構成。"""
    return {
        "header": {
            "target_unit": "R04CPU",
            "local_ip": "192.168.3.39",
        },
        "settings": [
            {
                "no": 1,
                "pattern": "Read",
                "schedule": "periodic",
                "interval": 100,
                "target": {
                    "device_type": "iQ-R",
                    "ip": "192.168.3.40",
                },
                "word_device": {
                    "src": {"type": "D", "start": 0, "end": 99},
                    "dst": {"type": "D", "start": 0, "end": 99},
                },
            }
        ],
    }


def test_missing_target_unit(base_config):
    base_config["header"].pop("target_unit")
    errors = gc.validate_config(base_config)
    assert any("target_unit" in e for e in errors)


def test_missing_local_ip(base_config):
    base_config["header"].pop("local_ip")
    errors = gc.validate_config(base_config)
    assert any("local_ip" in e for e in errors)


def test_invalid_local_ip_multicast(base_config):
    """224.x.x.x はマルチキャストで不可。"""
    base_config["header"]["local_ip"] = "224.0.0.1"
    errors = gc.validate_config(base_config)
    assert any("local_ip" in e and ("範囲" in e or "許容" in e) for e in errors)


def test_invalid_local_ip_zero(base_config):
    """0.0.0.0 は不可。"""
    base_config["header"]["local_ip"] = "0.0.0.0"
    errors = gc.validate_config(base_config)
    assert any("local_ip" in e for e in errors)


def test_invalid_ip_format(base_config):
    """未知の値は拒否。"""
    base_config["header"]["ip_format"] = "OCT"
    errors = gc.validate_config(base_config)
    assert any("ip_format" in e for e in errors)


def test_ip_format_hex_rejected(base_config):
    """iQ-RプロジェクトではHEXも拒否。GX Works3 のGUIで変更不可で10進数固定のため、
    HEX指定するとインポート時に行が破棄される。"""
    base_config["header"]["ip_format"] = "HEX"
    base_config["header"]["local_ip"] = "192.168.3.39"  # DECで書いたまま
    errors = gc.validate_config(base_config)
    assert any("ip_format" in e for e in errors)


def test_invalid_device_assignment(base_config):
    base_config["header"]["device_assignment"] = "Foo"
    errors = gc.validate_config(base_config)
    assert any("device_assignment" in e for e in errors)


def test_comm_start_wait_out_of_range(base_config):
    base_config["header"]["comm_start_wait"] = 256
    errors = gc.validate_config(base_config)
    assert any("comm_start_wait" in e for e in errors)


def test_initial_comm_invalid(base_config):
    base_config["header"]["initial_comm"] = "yes"
    errors = gc.validate_config(base_config)
    assert any("initial_comm" in e for e in errors)


def test_setting_no_duplicate(base_config):
    s1 = base_config["settings"][0]
    s2 = copy.deepcopy(s1)
    base_config["settings"].append(s2)
    errors = gc.validate_config(base_config)
    assert any("重複" in e for e in errors)


def test_setting_no_out_of_range(base_config):
    base_config["settings"][0]["no"] = 65
    errors = gc.validate_config(base_config)
    assert any("no" in e for e in errors)


def test_pattern_required(base_config):
    base_config["settings"][0].pop("pattern")
    errors = gc.validate_config(base_config)
    assert any("pattern" in e for e in errors)


def test_invalid_pattern(base_config):
    base_config["settings"][0]["pattern"] = "Both"
    errors = gc.validate_config(base_config)
    assert any("pattern" in e for e in errors)


def test_schedule_required(base_config):
    base_config["settings"][0].pop("schedule")
    errors = gc.validate_config(base_config)
    assert any("schedule" in e for e in errors)


def test_periodic_without_interval(base_config):
    """periodic 時に interval 欠落はエラー。"""
    base_config["settings"][0].pop("interval")
    errors = gc.validate_config(base_config)
    assert any("interval" in e for e in errors)


def test_periodic_interval_out_of_range(base_config):
    base_config["settings"][0]["interval"] = 9
    errors = gc.validate_config(base_config)
    assert any("interval" in e for e in errors)


def test_request_with_interval_forbidden(base_config):
    """request 時に interval 指定はエラー。"""
    base_config["settings"][0]["schedule"] = "request"
    base_config["settings"][0]["interval"] = 100
    errors = gc.validate_config(base_config)
    assert any("interval" in e for e in errors)


def test_request_with_error_monitor_forbidden(base_config):
    """request 時に error_monitor_sec 指定はエラー。"""
    base_config["settings"][0]["schedule"] = "request"
    base_config["settings"][0].pop("interval")
    base_config["settings"][0]["error_monitor_sec"] = 30
    errors = gc.validate_config(base_config)
    assert any("error_monitor_sec" in e for e in errors)


def test_target_ip_required(base_config):
    base_config["settings"][0]["target"].pop("ip")
    errors = gc.validate_config(base_config)
    assert any("target.ip" in e for e in errors)


def test_invalid_device_type_code(base_config):
    base_config["settings"][0]["target"]["device_type"] = 99
    errors = gc.validate_config(base_config)
    assert any("機器種別" in e for e in errors)


def test_invalid_device_type_alias(base_config):
    base_config["settings"][0]["target"]["device_type"] = "Siemens"
    errors = gc.validate_config(base_config)
    assert any("機器種別" in e for e in errors)


def test_tcp_must_be_udp(base_config):
    base_config["settings"][0]["target"]["tcp_udp"] = "TCP"
    errors = gc.validate_config(base_config)
    assert any("tcp_udp" in e for e in errors)


def test_port_forbidden_for_iqr(base_config):
    """iQ-R(16) では port 指定不可。"""
    base_config["settings"][0]["target"]["port"] = 5000
    errors = gc.validate_config(base_config)
    assert any("port" in e for e in errors)


def test_port_required_for_aans(base_config):
    """A/AnS(25) では port 必須。"""
    base_config["settings"][0]["target"]["device_type"] = "A"
    # word_device を A/AnS の有効範囲に変更
    base_config["settings"][0]["word_device"] = {
        "src": {"type": "D", "start": 0, "end": 9},
        "dst": {"type": "D", "start": 0, "end": 9},
    }
    errors = gc.validate_config(base_config)
    assert any("port" in e for e in errors)


def test_local_port_out_of_range_aans(base_config):
    """A/AnS の local_port は [1-4999]/[5010-65534]。5000 は範囲外。"""
    base_config["settings"][0]["target"]["device_type"] = "A"
    base_config["settings"][0]["target"]["port"] = 5000
    base_config["settings"][0]["target"]["local_port"] = 5000
    base_config["settings"][0]["word_device"] = {
        "src": {"type": "D", "start": 0, "end": 9},
        "dst": {"type": "D", "start": 0, "end": 9},
    }
    errors = gc.validate_config(base_config)
    assert any("local_port" in e for e in errors)


def test_option_hex_must_be_blank(base_config):
    """iQ-Rプロジェクトでは option_hex は GUI で変更不可で常に空欄。
    値を指定すると GX Works3 がインポート時に行を破棄するためエラー。"""
    base_config["settings"][0]["target"]["option_hex"] = "FFFF"
    errors = gc.validate_config(base_config)
    assert any("option_hex" in e for e in errors)


def test_option_hex_blank_ok(base_config):
    """option_hex を省略 / 空文字列にすればOK。"""
    base_config["settings"][0]["target"]["option_hex"] = ""
    errors = gc.validate_config(base_config)
    assert errors == []


def test_target_cpu_no_out_of_range(base_config):
    base_config["settings"][0]["target"]["cpu_no"] = 9
    errors = gc.validate_config(base_config)
    assert any("cpu_no" in e for e in errors)


def test_bit_start_not_multiple_of_16(base_config):
    """ビットデバイス先頭は16の倍数または0。M5 はNG。"""
    base_config["settings"][0]["bit_device"] = {
        "points": 16,
        "src": {"type": "M", "start": 5, "end": 20},
        "dst": {"type": "M", "start": 0, "end": 15},
    }
    base_config["settings"][0].pop("word_device")
    errors = gc.validate_config(base_config)
    assert any("16の倍数" in e for e in errors)


def test_bit_points_not_multiple_of_16(base_config):
    base_config["settings"][0]["bit_device"] = {
        "points": 17,
        "src": {"type": "M", "start": 0, "end": 16},
        "dst": {"type": "M", "start": 0, "end": 16},
    }
    base_config["settings"][0].pop("word_device")
    errors = gc.validate_config(base_config)
    assert any("16の倍数" in e for e in errors)


def test_word_points_too_large(base_config):
    """ワード513点は1設定上限512を超える。"""
    base_config["settings"][0]["word_device"] = {
        "points": 513,
        "src": {"type": "D", "start": 0, "end": 512},
        "dst": {"type": "D", "start": 0, "end": 512},
    }
    errors = gc.validate_config(base_config)
    assert any("512" in e or "上限" in e for e in errors)


def test_partner_ts_only_in_read(base_config):
    """相手側 TS は Read 時のみ可。Write でTSを置くとエラー。"""
    base_config["settings"][0]["pattern"] = "Write"
    base_config["settings"][0].pop("word_device")
    base_config["settings"][0]["bit_device"] = {
        "points": 16,
        "src": {"type": "M", "start": 0, "end": 15},  # 自局
        "dst": {"type": "TS", "start": 0, "end": 15},  # 相手TSはWriteで不可
    }
    errors = gc.validate_config(base_config)
    assert any("TS" in e for e in errors)


def test_own_ts_only_in_write(base_config):
    """自局側 TS は Write 時のみ可。Read で自局にTSを置くとエラー。"""
    base_config["settings"][0]["pattern"] = "Read"
    base_config["settings"][0].pop("word_device")
    base_config["settings"][0]["bit_device"] = {
        "points": 16,
        "src": {"type": "M", "start": 0, "end": 15},  # 相手
        "dst": {"type": "TS", "start": 0, "end": 15},  # 自局TSはReadで不可
    }
    errors = gc.validate_config(base_config)
    assert any("TS" in e for e in errors)


def test_end_mismatch_with_points(base_config):
    """end が points と整合しないとエラー。"""
    base_config["settings"][0]["word_device"] = {
        "points": 100,
        "src": {"type": "D", "start": 0, "end": 50},  # end=99 のはず
        "dst": {"type": "D", "start": 0, "end": 99},
    }
    errors = gc.validate_config(base_config)
    assert any("end" in e or "最終" in e for e in errors)


def test_total_words_over_8192(base_config):
    """ファイル全体ワード換算合計が 8192 を超えるとエラー。"""
    # 設定を多数生成して合計を超過させる
    settings = []
    for i in range(1, 18):  # 17件 * 512 = 8704 > 8192
        settings.append({
            "no": i,
            "pattern": "Read",
            "schedule": "periodic",
            "interval": 100,
            "target": {"device_type": "iQ-R", "ip": "192.168.3.40"},
            "word_device": {
                "points": 512,
                "src": {"type": "D", "start": 0, "end": 511},
                "dst": {"type": "D", "start": i * 1000, "end": i * 1000 + 511},
            },
        })
    base_config["settings"] = settings
    errors = gc.validate_config(base_config)
    assert any("8192" in e or "ファイル上限" in e for e in errors)


def test_iqf_x_octal_ok(base_config):
    """iQ-F の X は8進数。"0"-"37" (=10進0-31) はOK。"""
    base_config["settings"][0]["target"]["device_type"] = "iQ-F"
    base_config["settings"][0].pop("word_device")
    base_config["settings"][0]["bit_device"] = {
        "points": 32,
        "src": {"type": "X", "start": "0", "end": "37"},
        "dst": {"type": "M", "start": 0, "end": 31},
    }
    errors = gc.validate_config(base_config)
    assert errors == []
