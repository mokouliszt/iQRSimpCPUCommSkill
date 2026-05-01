# -*- coding: utf-8 -*-
"""
parse_csv の逆方向変換テスト。

- CSVを parse → JSON設定
- JSON設定 → generate → CSV
で **バイト一致** することをfixtureごとに確認（ラウンドトリップ）。
"""

from __future__ import annotations

import codecs
import json
from pathlib import Path

import pytest

import generate_csv as gc

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

ALL_FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_generate_then_parse_roundtrip_header(fx, tmp_path):
    """生成したCSVをparseするとヘッダー要素が元のJSONと一致する。"""
    cfg = json.loads(fx.read_text(encoding="utf-8"))
    out = tmp_path / f"{fx.stem}.csv"
    gc.generate_csv(cfg, out)
    parsed = gc.parse_csv(out)

    h_in = cfg["header"]
    h_out = parsed["header"]
    # 必須キー
    assert h_out["target_unit"] == h_in["target_unit"]
    assert h_out["local_ip"] == h_in["local_ip"]
    # title はファイル中で空であってもラウンドトリップ
    assert h_out.get("title", "") == h_in.get("title", "")
    # ip_format / device_assignment / initial_comm はデフォルトを含めて一致
    assert h_out["ip_format"] == h_in.get("ip_format", "DEC")
    assert h_out["device_assignment"] == h_in.get("device_assignment", "Start/End")
    assert h_out["initial_comm"] == h_in.get("initial_comm", "Disable")
    assert int(h_out["comm_start_wait"]) == int(h_in.get("comm_start_wait", 0))


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_generate_then_parse_settings_count(fx, tmp_path):
    """parse 結果の settings 件数が元と一致する。"""
    cfg = json.loads(fx.read_text(encoding="utf-8"))
    out = tmp_path / f"{fx.stem}.csv"
    gc.generate_csv(cfg, out)
    parsed = gc.parse_csv(out)
    assert len(parsed["settings"]) == len(cfg["settings"])


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_byte_identical_roundtrip(fx, tmp_path):
    """CSV → parse → generate でバイト一致することを確認。

    生成→parse→再generate で全く同じバイト列になればOK。
    """
    cfg = json.loads(fx.read_text(encoding="utf-8"))
    out1 = tmp_path / f"{fx.stem}_a.csv"
    out2 = tmp_path / f"{fx.stem}_b.csv"

    gc.generate_csv(cfg, out1)
    parsed = gc.parse_csv(out1)
    gc.generate_csv(parsed, out2)

    assert out1.read_bytes() == out2.read_bytes()


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda p: p.stem)
def test_setting_no_and_pattern_preserved(fx, tmp_path):
    """各設定の no / pattern / schedule がparse後も保持される。"""
    cfg = json.loads(fx.read_text(encoding="utf-8"))
    out = tmp_path / f"{fx.stem}.csv"
    gc.generate_csv(cfg, out)
    parsed = gc.parse_csv(out)
    for orig, got in zip(cfg["settings"], parsed["settings"]):
        assert got["no"] == orig["no"]
        assert got["pattern"] == orig["pattern"]
        assert got["schedule"] == orig["schedule"]


def test_parse_committed_sample_then_regen_matches():
    """samples/*.csv を直接parse→generateした結果が、元のサンプルとバイト一致する。"""
    import tempfile
    for sample in sorted(SAMPLES_DIR.glob("*.csv")):
        parsed = gc.parse_csv(sample)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as t:
            tmp_path = Path(t.name)
        try:
            gc.generate_csv(parsed, tmp_path)
            assert tmp_path.read_bytes() == sample.read_bytes(), \
                f"{sample.name}: parse→generateでバイト一致しない"
        finally:
            tmp_path.unlink(missing_ok=True)


def test_parse_handles_utf16_be_bom(tmp_path):
    """UTF-16 BE BOMでも読めること（GX Works3はLEだが、念のため）。"""
    # 最小のCSVをUTF-16 BEで書いてparseできるか
    cfg = {
        "header": {"target_unit": "R04CPU", "local_ip": "192.168.3.39"},
        "settings": [
            {
                "no": 1, "pattern": "Read", "schedule": "periodic", "interval": 100,
                "target": {"device_type": "iQ-R", "ip": "192.168.3.40"},
                "word_device": {
                    "src": {"type": "D", "start": 0, "end": 99},
                    "dst": {"type": "D", "start": 0, "end": 99},
                },
            }
        ],
    }
    le_path = tmp_path / "le.csv"
    gc.generate_csv(cfg, le_path)
    text = le_path.read_bytes()[2:].decode("utf-16-le")
    be_path = tmp_path / "be.csv"
    be_path.write_bytes(codecs.BOM_UTF16_BE + text.encode("utf-16-be"))
    parsed = gc.parse_csv(be_path)
    assert parsed["header"]["target_unit"] == "R04CPU"
    assert len(parsed["settings"]) == 1
