#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MELSEC iQ-R シンプルCPU通信(内蔵Ethernet) 設定CSV ジェネレータ／バリデータ。

GX Works3 の "シンプルCPU通信設定" 画面でインポート／エクスポートできる
タブ区切り UTF-16LE(BOM付) CSV を生成・検証・逆解析する。

サブコマンド:
    generate   <config.json> <out.csv>   JSONからCSVを生成（生成前に検証）
    validate   <config.json>             JSONを検証のみ（CSVは書かない）
    parse      <in.csv> [<out.json>]     既存CSVをJSON設定にデコード

JSON設定の最小例:
    {
      "header": {
        "target_unit": "R04CPU",
        "local_ip": "192.168.3.39"
      },
      "settings": [
        {"no": 1, "pattern": "Read", "schedule": "periodic", "interval": 100,
         "target": {"device_type": "iQ-R", "ip": "192.168.3.40"},
         "word_device": {"src": {"type": "D", "start": 0, "end": 99},
                         "dst": {"type": "D", "start": 0, "end": 99}}}
      ]
    }

詳細仕様: references/csv_format.md, references/validation_rules.md
"""

from __future__ import annotations

import argparse
import codecs
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any

# ============================================================
# 定数とデータロード
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DEVICE_RANGES_PATH = SCRIPT_DIR / "device_ranges.json"

# 29カラム: GX Works3エクスポートと同じ並び順（必須）
COLUMN_HEADERS = [
    "設定No.",
    "通信パターン",
    "交信設定",
    "実行間隔",
    "交信相手設定：機器種別",
    "交信相手設定：IPアドレス",
    "交信相手設定：TCP/UDP",
    "交信相手設定：ポート番号",
    "交信相手設定：自局ポート番号",
    "交信相手設定：オプション(16進数)",
    "対象号機",
    "ビットデバイス：点数",
    "ビットデバイス：転送元種別",
    "ビットデバイス：転送元先頭",
    "ビットデバイス：転送元最終",
    "ビットデバイス：転送先種別",
    "ビットデバイス：転送先先頭",
    "ビットデバイス：転送先最終",
    "ワードデバイス：点数",
    "ワードデバイス：転送元種別",
    "ワードデバイス：転送元先頭",
    "ワードデバイス：転送元最終",
    "ワードデバイス：転送先種別",
    "ワードデバイス：転送先先頭",
    "ワードデバイス：転送先最終",
    "通信タイムアウト時間",
    "通信リトライ回数",
    "異常監視時間",
    "コメント",
]

# ヘッダー行(行1～8)のキー名（順序保持）
# 行2は単一フィールドの "label" — 名前なし
HEADER_KEYS = [
    ("ファイルバージョン", "file_version"),     # 行1
    None,                                          # 行2: title (ラベル) — 単フィールド
    ("対象ユニット", "target_unit"),               # 行3
    ("自局IPアドレス", "local_ip"),                # 行4
    ("IPアドレス入力形式", "ip_format"),           # 行5
    ("デバイス割付方法", "device_assignment"),     # 行6
    ("通信開始待ち時間", "comm_start_wait"),       # 行7
    ("初回交信設定", "initial_comm"),              # 行8
]

# CSVに格納されるリテラル値（PDF p.230のマッピング表）
SCHEDULE_TO_CSV = {"request": "0", "要求時": "0", "periodic": "1", "定期": "1"}
CSV_TO_SCHEDULE = {"0": "request", "1": "periodic"}

PATTERN_TO_CSV = {"Read": "Read", "読出": "Read", "read": "Read",
                  "Write": "Write", "書込": "Write", "write": "Write"}

DEFAULT_HEADER = {
    "file_version": "1",
    "title": "",
    "target_unit": "",
    "local_ip": "",
    "ip_format": "DEC",
    "device_assignment": "Start/End",
    "comm_start_wait": 0,
    "initial_comm": "Disable",
}

DEFAULT_SETTING = {
    "tcp_udp": "UDP",
    "target_cpu": 0,
    "timeout_ms": 1000,
    "retry_count": 3,
    "error_monitor_sec": 30,
    "option_hex": "",
    "comment": "",
}


def load_device_ranges() -> dict:
    """device_ranges.jsonをロードし、_alias_ofを実体に展開する。"""
    with open(DEVICE_RANGES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # _alias_of を展開
    pd = data["partner_devices"]
    for code, body in list(pd.items()):
        if isinstance(body, dict) and "_alias_of" in body:
            target = body["_alias_of"]
            if target in pd and "_alias_of" not in pd[target]:
                pd[code] = pd[target]
    return data


# ============================================================
# 共通ユーティリティ
# ============================================================


class ValidationError(Exception):
    """設定検証エラー。errors リストを保持する。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:5]) + ("..." if len(errors) > 5 else ""))
        self.errors = errors


def _is_in_ranges(value: int, ranges: list[list[int]]) -> bool:
    """value が [[lo,hi], ...] のいずれかの閉区間に入るか。"""
    for lo, hi in ranges:
        if lo <= value <= hi:
            return True
    return False


def _parse_int_with_base(s: Any, base: int, ctx: str, errors: list[str]) -> int | None:
    """文字列または整数を指定基数で整数に変換。失敗時は errors に追記し None を返す。"""
    if s is None or s == "":
        errors.append(f"{ctx}: 値が空です")
        return None
    if isinstance(s, int):
        return s
    s = str(s).strip()
    try:
        return int(s, base)
    except ValueError:
        bn = {8: "8進数", 10: "10進数", 16: "16進数"}.get(base, f"基数{base}")
        errors.append(f"{ctx}: '{s}' は{bn}として解釈できません")
        return None


def _format_int_with_base(value: int, base: int) -> str:
    """整数を指定基数の最短文字列にフォーマット（パディングなし、大文字hex）。"""
    if base == 16:
        return f"{value:X}"
    if base == 8:
        return f"{value:o}"
    return str(value)


def _ip_to_csv(ip_str: str, ip_format: str) -> str:
    """IPアドレスをCSV格納形式に変換。"""
    if ip_format == "HEX":
        ip = ipaddress.IPv4Address(ip_str)
        return f"{int(ip):08X}"
    return ip_str  # DEC: そのまま


def _ip_from_csv(s: str, ip_format: str) -> str:
    """CSV格納形式のIPをドット表記に正規化（DECならそのまま）。"""
    if ip_format == "HEX":
        if not re.fullmatch(r"[0-9A-Fa-f]{8}", s):
            return s  # 不正なら原文返す（呼出側で検証）
        return str(ipaddress.IPv4Address(int(s, 16)))
    return s


def _validate_ipv4(ip_str: str, ctx: str, errors: list[str]) -> None:
    """0.0.0.1～223.255.255.254 の範囲かチェック。"""
    try:
        ip = ipaddress.IPv4Address(ip_str)
    except (ipaddress.AddressValueError, ValueError):
        errors.append(f"{ctx}: '{ip_str}' は有効なIPv4アドレスではありません")
        return
    n = int(ip)
    if not (1 <= n <= 0xDFFFFFFE):  # 0.0.0.1 ~ 223.255.255.254
        errors.append(f"{ctx}: '{ip_str}' は許容範囲(0.0.0.1～223.255.255.254)外")


def _normalize_device_type(device_type: Any, errors: list[str], ranges: dict) -> int | None:
    """機器種別（数値コード or 文字列エイリアス）を数値コードに正規化。"""
    if device_type is None:
        errors.append("交信相手.機器種別: 必須です")
        return None
    if isinstance(device_type, int):
        code = device_type
    elif isinstance(device_type, str):
        s = device_type.strip()
        # エイリアス検索
        if s in ranges["device_type_alias"]:
            code = ranges["device_type_alias"][s]
        else:
            try:
                code = int(s)
            except ValueError:
                errors.append(f"交信相手.機器種別: '{s}' は不明な機器種別")
                return None
    else:
        errors.append(f"交信相手.機器種別: 型が不正 ({type(device_type).__name__})")
        return None
    if str(code) not in ranges["device_type_codes"]:
        valid = ", ".join(sorted(ranges["device_type_codes"].keys(), key=int))
        errors.append(f"交信相手.機器種別: コード {code} は無効。有効値: {valid}")
        return None
    return code


# ============================================================
# 検証本体
# ============================================================


def validate_config(config: dict) -> list[str]:
    """設定dict全体を検証し、エラー文字列のリストを返す（空なら検証OK）。"""
    errors: list[str] = []
    ranges = load_device_ranges()
    consts = ranges["header_constants"]

    # ---- ヘッダー検証 ----
    header = config.get("header", {})
    if not isinstance(header, dict):
        return ["header: dictである必要があります"]

    # target_unit
    if not header.get("target_unit"):
        errors.append("header.target_unit: 必須（例: R04CPU）")

    # local_ip
    if not header.get("local_ip"):
        errors.append("header.local_ip: 必須")
    else:
        _validate_ipv4(header["local_ip"], "header.local_ip", errors)

    # ip_format
    # iQ-Rプロジェクトでは10進数固定。GUIで変更不可なので CSV も "DEC" のみ受け付ける。
    ipf = header.get("ip_format", DEFAULT_HEADER["ip_format"])
    if ipf != "DEC":
        errors.append(
            f"header.ip_format: '{ipf}' は無効。"
            "iQ-Rプロジェクトでは 'DEC' (10進数) のみサポート。"
            "GX Works3 のシンプルCPU通信設定では IPアドレス入力形式 が変更不可で 10進数固定のため、"
            "HEX を指定すると GX Works3 がインポート時に行を破棄する。"
        )

    # device_assignment
    da = header.get("device_assignment", DEFAULT_HEADER["device_assignment"])
    if da not in consts["device_assignment_values"]:
        errors.append(f"header.device_assignment: '{da}' は無効。{consts['device_assignment_values']}のいずれか")

    # comm_start_wait
    csw = header.get("comm_start_wait", DEFAULT_HEADER["comm_start_wait"])
    try:
        csw_i = int(csw)
        if not (consts["comm_start_wait_min_sec"] <= csw_i <= consts["comm_start_wait_max_sec"]):
            errors.append(
                f"header.comm_start_wait: {csw_i}は範囲外 "
                f"({consts['comm_start_wait_min_sec']}～{consts['comm_start_wait_max_sec']}秒)"
            )
    except (ValueError, TypeError):
        errors.append(f"header.comm_start_wait: 整数で指定してください（'{csw}'）")

    # initial_comm
    ic = header.get("initial_comm", DEFAULT_HEADER["initial_comm"])
    if ic not in consts["initial_comm_values"]:
        errors.append(f"header.initial_comm: '{ic}' は無効。{consts['initial_comm_values']}のいずれか")

    # ---- 設定リスト検証 ----
    settings = config.get("settings", [])
    if not isinstance(settings, list):
        return errors + ["settings: list であること"]
    if len(settings) == 0:
        errors.append("settings: 少なくとも1件は必要")
    if len(settings) > consts["setting_no_max"]:
        errors.append(f"settings: 最大{consts['setting_no_max']}件まで（現在 {len(settings)}）")

    seen_nos = set()
    total_words = 0
    for idx, s in enumerate(settings, start=1):
        ctx_root = f"settings[{idx}]"
        if not isinstance(s, dict):
            errors.append(f"{ctx_root}: dictであること")
            continue
        no = s.get("no")
        if no is None:
            errors.append(f"{ctx_root}.no: 必須")
        else:
            try:
                no_i = int(no)
                if not (consts["setting_no_min"] <= no_i <= consts["setting_no_max"]):
                    errors.append(f"{ctx_root}.no: {no_i}は範囲外 (1～64)")
                if no_i in seen_nos:
                    errors.append(f"{ctx_root}.no: {no_i} は他の設定と重複")
                seen_nos.add(no_i)
            except (ValueError, TypeError):
                errors.append(f"{ctx_root}.no: 整数で指定してください")
                no_i = None

        # 通信パターン
        pat = s.get("pattern")
        pat_csv = PATTERN_TO_CSV.get(str(pat)) if pat is not None else None
        if pat_csv is None:
            errors.append(f"{ctx_root}.pattern: 必須かつ 'Read' または 'Write'")

        # 交信設定（schedule）
        sched = s.get("schedule")
        sched_csv = SCHEDULE_TO_CSV.get(str(sched)) if sched is not None else None
        if sched_csv is None:
            errors.append(f"{ctx_root}.schedule: 必須かつ 'periodic' または 'request'")

        # 実行間隔
        interval = s.get("interval")
        if sched_csv == "1":  # periodic
            if interval is None:
                errors.append(f"{ctx_root}.interval: 'periodic'時は必須（10～65535ms）")
            else:
                try:
                    iv = int(interval)
                    if not (consts["interval_min_ms"] <= iv <= consts["interval_max_ms"]):
                        errors.append(
                            f"{ctx_root}.interval: {iv}は範囲外 "
                            f"({consts['interval_min_ms']}～{consts['interval_max_ms']}ms)"
                        )
                except (ValueError, TypeError):
                    errors.append(f"{ctx_root}.interval: 整数で指定してください")
        else:  # request
            if interval not in (None, "", 0):
                errors.append(f"{ctx_root}.interval: 'request'時は空にしてください")

        # 交信相手設定
        target = s.get("target", {})
        if not isinstance(target, dict):
            errors.append(f"{ctx_root}.target: dictであること")
            target = {}

        dt_code = _normalize_device_type(target.get("device_type"), errors, ranges)

        if not target.get("ip"):
            errors.append(f"{ctx_root}.target.ip: 必須")
        else:
            _validate_ipv4(target["ip"], f"{ctx_root}.target.ip", errors)

        # TCP/UDP
        tu = target.get("tcp_udp", DEFAULT_SETTING["tcp_udp"])
        if tu != "UDP":
            errors.append(f"{ctx_root}.target.tcp_udp: 'UDP' のみサポート（現在 '{tu}'）")

        # ポート番号 / 自局ポート番号
        if dt_code is not None:
            rule = ranges["port_rules"][str(dt_code)]
            for fld_name, key in [("port", "port"), ("local_port", "local_port")]:
                v = target.get(key)
                rng = rule[key]
                ctx = f"{ctx_root}.target.{key}"
                if rng == "forbidden":
                    if v not in (None, "", 0):
                        errors.append(f"{ctx}: 機器種別 {dt_code} ではポート設定不可（空にする）")
                else:
                    if v in (None, ""):
                        errors.append(f"{ctx}: 機器種別 {dt_code} では必須")
                    else:
                        try:
                            vi = int(v)
                            if not _is_in_ranges(vi, rng):
                                rngs = ", ".join(f"{lo}-{hi}" for lo, hi in rng)
                                errors.append(f"{ctx}: {vi} は範囲外（{rngs}）")
                        except (ValueError, TypeError):
                            errors.append(f"{ctx}: 整数で指定してください")

        # オプション(16進数)
        # iQ-Rプロジェクトでは GUI で変更不可で常に空欄。CSV出力でも空欄でなければならない。
        opt = target.get("option_hex", "")
        if opt not in (None, ""):
            errors.append(
                f"{ctx_root}.target.option_hex: '{opt}' は無効。"
                "iQ-Rプロジェクトでは オプション(16進数) は GUI で変更不可で常に空欄のため、"
                "CSV にも空欄を出す必要がある。値を指定すると GX Works3 がインポート時に行を破棄する。"
            )

        # 対象号機
        cpu_no = target.get("cpu_no", DEFAULT_SETTING["target_cpu"])
        try:
            cn = int(cpu_no)
            if not (consts["target_cpu_min"] <= cn <= consts["target_cpu_max"]):
                errors.append(f"{ctx_root}.target.cpu_no: {cn}は範囲外 (0～8)")
        except (ValueError, TypeError):
            errors.append(f"{ctx_root}.target.cpu_no: 整数で指定してください")

        # ビット/ワードデバイス
        bit_dev = s.get("bit_device")
        word_dev = s.get("word_device")
        if not bit_dev and not word_dev:
            errors.append(f"{ctx_root}: bit_device か word_device の少なくとも一方が必要")

        bit_pts = _validate_device_block(
            bit_dev, "bit", ctx_root, errors, ranges, dt_code, pat_csv,
            header.get("device_assignment", DEFAULT_HEADER["device_assignment"]),
        ) if bit_dev else 0
        word_pts = _validate_device_block(
            word_dev, "word", ctx_root, errors, ranges, dt_code, pat_csv,
            header.get("device_assignment", DEFAULT_HEADER["device_assignment"]),
        ) if word_dev else 0

        # 1設定あたりワード換算 ≤ 512
        words_this = (bit_pts // 16) + word_pts
        if words_this > consts["max_words_per_setting"]:
            errors.append(
                f"{ctx_root}: ワード換算合計 {words_this} が1設定あたり上限 "
                f"{consts['max_words_per_setting']} を超過"
            )
        total_words += words_this

        # ビット点数 ≤ 8192
        if bit_pts > consts["max_bit_points_per_setting"]:
            errors.append(
                f"{ctx_root}.bit_device.points: {bit_pts}が上限 "
                f"{consts['max_bit_points_per_setting']} を超過"
            )

        # タイムアウト・リトライ・異常監視
        for key, lo, hi in [
            ("timeout_ms", 1, 65535),
            ("retry_count", 0, 32),
        ]:
            v = s.get(key, DEFAULT_SETTING.get(key))
            if v is None:
                continue
            try:
                vi = int(v)
                if not (lo <= vi <= hi):
                    errors.append(f"{ctx_root}.{key}: {vi}は範囲外 ({lo}～{hi})")
            except (ValueError, TypeError):
                errors.append(f"{ctx_root}.{key}: 整数で指定してください")

        # 異常監視時間: periodicの時のみ意味を持つ
        em = s.get("error_monitor_sec")
        if sched_csv == "1":
            if em is not None and em != "":
                try:
                    emi = int(em)
                    if not (1 <= emi <= 65535):
                        errors.append(f"{ctx_root}.error_monitor_sec: {emi}は範囲外 (1～65535)")
                except (ValueError, TypeError):
                    errors.append(f"{ctx_root}.error_monitor_sec: 整数で指定してください")
        else:
            if em not in (None, "", 0):
                errors.append(f"{ctx_root}.error_monitor_sec: 'request'時は空にしてください")

    # ファイル全体ワード合計
    if total_words > consts["max_total_words_per_file"]:
        errors.append(
            f"全設定ワード換算合計 {total_words} がファイル上限 "
            f"{consts['max_total_words_per_file']} を超過"
        )

    return errors


def _validate_device_block(
    block: Any,
    kind: str,                # "bit" or "word"
    ctx_root: str,
    errors: list[str],
    ranges: dict,
    partner_code: int | None,
    pat_csv: str | None,
    assign: str,
) -> int:
    """ビット／ワードデバイスブロックを検証し、点数を返す。エラー時は0を返す。"""
    if not isinstance(block, dict):
        errors.append(f"{ctx_root}.{kind}_device: dictであること")
        return 0
    pts = _resolve_points(block, kind, ctx_root, errors, assign)
    if pts <= 0:
        return 0
    consts = ranges["header_constants"]
    if kind == "bit":
        if pts % 16 != 0:
            errors.append(f"{ctx_root}.bit_device.points: {pts}は16の倍数で指定")
        if pts < 16:
            errors.append(f"{ctx_root}.bit_device.points: 最小16点")
    else:
        if pts < 1:
            errors.append(f"{ctx_root}.word_device.points: 最小1点")

    src = block.get("src", {})
    dst = block.get("dst", {})
    if not isinstance(src, dict) or not isinstance(dst, dict):
        errors.append(f"{ctx_root}.{kind}_device: src/dstはdictであること")
        return pts

    # Read: 自局=dst, 相手=src
    # Write: 自局=src, 相手=dst
    if pat_csv == "Read":
        own_side, partner_side = dst, src
        own_label, partner_label = "dst(自局)", "src(相手)"
    elif pat_csv == "Write":
        own_side, partner_side = src, dst
        own_label, partner_label = "src(自局)", "dst(相手)"
    else:
        return pts  # patternエラーは別途報告済み

    own_rules = ranges["own_station"][kind]
    partner_rules = ranges["partner_devices"].get(str(partner_code), {}).get(kind, {}) \
        if partner_code is not None else {}

    _validate_one_side(
        own_side, kind, pts, own_rules, pat_csv,
        f"{ctx_root}.{kind}_device.{own_label}", errors,
    )
    _validate_one_side(
        partner_side, kind, pts, partner_rules, pat_csv,
        f"{ctx_root}.{kind}_device.{partner_label}", errors,
        partner_side_check=True,
    )
    return pts


def _resolve_points(block: dict, kind: str, ctx: str, errors: list[str], assign: str) -> int:
    """ブロックの points / src.start,end / dst.start,end を整合チェックして点数を返す。"""
    pts = block.get("points")
    src = block.get("src", {})
    dst = block.get("dst", {})
    src_start_raw = src.get("start") if isinstance(src, dict) else None
    src_end_raw = src.get("end") if isinstance(src, dict) else None

    # 種別が決まらないと start/end の基数が分からない。
    # ここでは "暫定的に" 10進数として整数化を試み、駄目なら 16進数で再試行する補助
    def _try_int(v):
        if v is None or v == "":
            return None
        if isinstance(v, int):
            return v
        s = str(v).strip()
        for b in (10, 16, 8):
            try:
                return int(s, b)
            except ValueError:
                continue
        return None

    if pts is not None:
        try:
            return int(pts)
        except (ValueError, TypeError):
            errors.append(f"{ctx}.{kind}_device.points: 整数で指定してください")
            return 0

    # points が無い → start/end から計算
    s_int = _try_int(src_start_raw)
    e_int = _try_int(src_end_raw)
    if s_int is not None and e_int is not None:
        if e_int < s_int:
            errors.append(f"{ctx}.{kind}_device.src: start({src_start_raw}) > end({src_end_raw})")
            return 0
        return e_int - s_int + 1

    errors.append(
        f"{ctx}.{kind}_device: pointsまたはsrc.start/src.endのいずれかが必要"
        f"（device_assignment={assign}）"
    )
    return 0


def _validate_one_side(
    side: dict,
    kind: str,
    pts: int,
    rules: dict,
    pat_csv: str | None,
    ctx: str,
    errors: list[str],
    partner_side_check: bool = False,
) -> None:
    """src または dst 単一辺を検証。"""
    sym = side.get("type")
    if not sym:
        errors.append(f"{ctx}.type: デバイス記号が必要")
        return
    sym = str(sym).strip().upper()
    if sym not in rules:
        errors.append(f"{ctx}.type: '{sym}' は対象機器種別では使用不可")
        return

    rule = rules[sym]
    base = rule["base"]

    # pattern_only 制約
    pat_only = rule.get("pattern_only")
    if pat_only and pat_csv and pat_only != pat_csv:
        side_kind = "相手" if partner_side_check else "自局"
        errors.append(
            f"{ctx}.type: '{sym}' は{side_kind}側では '通信パターン={pat_only}' 時のみ指定可"
        )

    start_raw = side.get("start")
    end_raw = side.get("end")
    s_int = _parse_int_with_base(start_raw, base, f"{ctx}.start", errors)
    if s_int is None:
        return

    # ビット先頭は16の倍数または0
    if kind == "bit" and s_int % 16 != 0:
        errors.append(f"{ctx}.start: ビットデバイス先頭は16の倍数または0（{start_raw}）")

    expected_end = s_int + max(pts - 1, 0)
    if end_raw not in (None, ""):
        e_int = _parse_int_with_base(end_raw, base, f"{ctx}.end", errors)
        if e_int is not None and e_int != expected_end:
            errors.append(
                f"{ctx}.end: 点数({pts})と先頭({start_raw})から計算される最終は "
                f"{_format_int_with_base(expected_end, base)} ですが '{end_raw}' が指定"
            )

    # 範囲チェック（先頭・最終ともCPU有効範囲内）
    rng = [[rule["min"], rule["max"]]]
    if "extra_ranges" in rule:
        rng.extend(rule["extra_ranges"])
    for label, val in [("start", s_int), ("end", expected_end)]:
        if not _is_in_ranges(val, rng):
            rng_disp = ", ".join(
                f"{_format_int_with_base(lo, base)}-{_format_int_with_base(hi, base)}"
                for lo, hi in rng
            )
            errors.append(
                f"{ctx}.{label}: '{_format_int_with_base(val, base)}' は "
                f"{sym}の有効範囲（{rng_disp}）外"
            )

    # A/AnSの M/D 9000~9255 は16の倍数+9000で指定（PDFに明記）
    if rule.get("extra_ranges"):
        for lo, hi in rule["extra_ranges"]:
            if lo <= s_int <= hi and lo == 9000 and (s_int - 9000) % 16 != 0:
                errors.append(
                    f"{ctx}.start: A/AnS の{sym}{lo}～{hi}範囲は (9000+16の倍数) で指定"
                )


# ============================================================
# CSV 生成
# ============================================================


def generate_csv(config: dict, output_path: str | Path) -> None:
    """検証＋CSV出力。検証NGなら ValidationError を投げる。"""
    errors = validate_config(config)
    if errors:
        raise ValidationError(errors)

    ranges = load_device_ranges()
    header = {**DEFAULT_HEADER, **config.get("header", {})}
    settings = config["settings"]

    rows: list[list[str]] = []

    # 行1～8: ヘッダー
    rows.append(["ファイルバージョン", str(header["file_version"])])
    rows.append([str(header.get("title", ""))])  # 行2: 単フィールド
    rows.append(["対象ユニット", str(header["target_unit"])])
    rows.append(["自局IPアドレス", _ip_to_csv(header["local_ip"], header["ip_format"])])
    rows.append(["IPアドレス入力形式", header["ip_format"]])
    rows.append(["デバイス割付方法", header["device_assignment"]])
    rows.append(["通信開始待ち時間", str(int(header["comm_start_wait"]))])
    rows.append(["初回交信設定", header["initial_comm"]])

    # 行9: カラム見出し
    rows.append(list(COLUMN_HEADERS))

    # 行10～: データ
    for s in settings:
        rows.append(_setting_to_csv_row(s, header, ranges))

    _write_csv(rows, Path(output_path))


def _setting_to_csv_row(s: dict, header: dict, ranges: dict) -> list[str]:
    """設定dict 1件を29カラムのCSV行に変換。"""
    target = s.get("target", {})
    pat = PATTERN_TO_CSV[str(s["pattern"])]
    sched = SCHEDULE_TO_CSV[str(s["schedule"])]
    interval = "" if sched == "0" else str(int(s["interval"]))

    dt_code = _normalize_device_type(target.get("device_type"), [], ranges)
    rule = ranges["port_rules"][str(dt_code)]
    port = "" if rule["port"] == "forbidden" else str(int(target.get("port") or 0))
    local_port = "" if rule["local_port"] == "forbidden" else str(int(target.get("local_port") or 0))
    if port == "0" and rule["port"] == "forbidden":
        port = ""
    if local_port == "0" and rule["local_port"] == "forbidden":
        local_port = ""

    bit = s.get("bit_device") or {}
    word = s.get("word_device") or {}

    bit_cells = _device_to_cells(bit, "bit", header, ranges, dt_code, pat) \
        if bit else ["", "", "", "", "", "", ""]
    word_cells = _device_to_cells(word, "word", header, ranges, dt_code, pat) \
        if word else ["", "", "", "", "", "", ""]

    em = s.get("error_monitor_sec", DEFAULT_SETTING["error_monitor_sec"])
    em_str = "" if sched == "0" or em in (None, "") else str(int(em))

    return [
        str(int(s["no"])),
        pat,
        sched,
        interval,
        str(dt_code),
        _ip_to_csv(target["ip"], header["ip_format"]),
        target.get("tcp_udp", DEFAULT_SETTING["tcp_udp"]),
        port,
        local_port,
        str(target.get("option_hex", "")),
        str(int(target.get("cpu_no", DEFAULT_SETTING["target_cpu"]))),
        *bit_cells,
        *word_cells,
        str(int(s.get("timeout_ms", DEFAULT_SETTING["timeout_ms"]))),
        str(int(s.get("retry_count", DEFAULT_SETTING["retry_count"]))),
        em_str,
        str(s.get("comment", "")),
    ]


def _device_to_cells(
    block: dict, kind: str, header: dict, ranges: dict,
    partner_code: int | None, pat_csv: str,
) -> list[str]:
    """device block を [points, src_type, src_start, src_end, dst_type, dst_start, dst_end] に。"""
    pts = block.get("points")
    src = block.get("src", {})
    dst = block.get("dst", {})

    # 種別から base を解決して start/end を整える
    def fmt_side(side: dict, side_rules: dict) -> tuple[str, str, str]:
        sym = str(side.get("type", "")).upper()
        rule = side_rules.get(sym, {"base": 10})
        base = rule.get("base", 10)
        s_int = _parse_int_with_base(side.get("start"), base, "_dummy", [])
        if s_int is None:
            return sym, "", ""
        if pts is not None:
            e_int = s_int + int(pts) - 1
        else:
            e_int = _parse_int_with_base(side.get("end"), base, "_dummy", [])
            if e_int is None:
                e_int = s_int
        # X/Y のビット devices で 5桁ゼロパディングを採用（GX Works3 流儀に近づける）
        if kind == "bit" and base == 16 and sym in ("X", "Y"):
            return sym, f"{s_int:05X}", f"{e_int:05X}"
        return sym, _format_int_with_base(s_int, base), _format_int_with_base(e_int, base)

    own_rules = ranges["own_station"][kind]
    partner_rules = ranges["partner_devices"].get(str(partner_code), {}).get(kind, {}) \
        if partner_code is not None else {}

    if pat_csv == "Read":
        # src=相手, dst=自局
        src_sym, src_st, src_en = fmt_side(src, partner_rules)
        dst_sym, dst_st, dst_en = fmt_side(dst, own_rules)
    else:
        src_sym, src_st, src_en = fmt_side(src, own_rules)
        dst_sym, dst_st, dst_en = fmt_side(dst, partner_rules)

    # 点数決定
    if pts is None:
        s_int = _parse_int_with_base(src.get("start"), partner_rules.get(src_sym, own_rules.get(src_sym, {"base": 10}))["base"], "_d", [])
        e_int = _parse_int_with_base(src.get("end"), partner_rules.get(src_sym, own_rules.get(src_sym, {"base": 10}))["base"], "_d", [])
        if s_int is not None and e_int is not None:
            pts = e_int - s_int + 1
    pts_str = str(int(pts)) if pts else ""

    return [pts_str, src_sym, src_st, src_en, dst_sym, dst_st, dst_en]


def _write_csv(rows: list[list[str]], path: Path) -> None:
    """UTF-16LE BOM付・タブ区切り・"" 引用・CRLF で書き出す。"""
    out_lines: list[str] = []
    for row in rows:
        # 各セルを "..." で囲む。内部の " は "" にエスケープ
        cells = ['"' + str(c).replace('"', '""') + '"' for c in row]
        out_lines.append("\t".join(cells))
    body = "\r\n".join(out_lines) + "\r\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(codecs.BOM_UTF16_LE)
        f.write(body.encode("utf-16-le"))


# ============================================================
# CSV 解析（逆方向）
# ============================================================


def parse_csv(path: str | Path) -> dict:
    """既存のシンプルCPU通信CSVを読み、設定dictに復元。"""
    raw = Path(path).read_bytes()
    # BOM判定
    if raw.startswith(codecs.BOM_UTF16_LE):
        text = raw[2:].decode("utf-16-le")
    elif raw.startswith(codecs.BOM_UTF16_BE):
        text = raw[2:].decode("utf-16-be")
    elif raw.startswith(codecs.BOM_UTF8):
        text = raw[3:].decode("utf-8")
    else:
        # フォールバック
        text = raw.decode("utf-16-le", errors="replace")

    lines = text.split("\r\n")
    # 末尾の空行を取り除く
    while lines and lines[-1] == "":
        lines.pop()

    def split_row(line: str) -> list[str]:
        # タブ区切り、各セルは "..." で囲まれる。"" は " にデコード
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

    if len(lines) < 9:
        raise ValueError(f"CSVの行数が不足（{len(lines)}行）。最低9行のヘッダーが必要")

    header = dict(DEFAULT_HEADER)
    # 行1
    r = split_row(lines[0])
    header["file_version"] = r[1] if len(r) > 1 else "1"
    # 行2
    r = split_row(lines[1])
    header["title"] = r[0] if r else ""
    # 行3
    r = split_row(lines[2])
    header["target_unit"] = r[1] if len(r) > 1 else ""
    # 行4
    r = split_row(lines[3])
    raw_ip = r[1] if len(r) > 1 else ""
    # 行5
    r = split_row(lines[4])
    header["ip_format"] = r[1] if len(r) > 1 else "DEC"
    header["local_ip"] = _ip_from_csv(raw_ip, header["ip_format"])
    # 行6
    r = split_row(lines[5])
    header["device_assignment"] = r[1] if len(r) > 1 else "Start/End"
    # 行7
    r = split_row(lines[6])
    try:
        header["comm_start_wait"] = int(r[1]) if len(r) > 1 else 0
    except ValueError:
        header["comm_start_wait"] = 0
    # 行8
    r = split_row(lines[7])
    header["initial_comm"] = r[1] if len(r) > 1 else "Disable"

    # 行9: 列見出し（無視。GX Works3固定）
    # 行10以降: データ
    settings: list[dict] = []
    for raw_line in lines[9:]:
        if not raw_line.strip():
            continue
        cols = split_row(raw_line)
        if len(cols) < len(COLUMN_HEADERS):
            cols += [""] * (len(COLUMN_HEADERS) - len(cols))
        s = _row_to_setting(cols, header)
        settings.append(s)

    return {"header": header, "settings": settings}


def _row_to_setting(c: list[str], header: dict) -> dict:
    """CSVデータ行29カラムを設定dictに変換。"""
    pat = c[1] or "Read"
    sched_csv = c[2] or "0"

    setting: dict = {
        "no": int(c[0]) if c[0] else None,
        "pattern": pat,
        "schedule": CSV_TO_SCHEDULE.get(sched_csv, "request"),
        "interval": int(c[3]) if c[3] else None,
        "target": {
            "device_type": int(c[4]) if c[4] else None,
            "ip": _ip_from_csv(c[5], header["ip_format"]),
            "tcp_udp": c[6] or "UDP",
            "port": int(c[7]) if c[7] else None,
            "local_port": int(c[8]) if c[8] else None,
            "option_hex": c[9],
            "cpu_no": int(c[10]) if c[10] else 0,
        },
        "timeout_ms": int(c[25]) if c[25] else None,
        "retry_count": int(c[26]) if c[26] else None,
        "error_monitor_sec": int(c[27]) if c[27] else None,
        "comment": c[28],
    }

    # ビットデバイス
    if any(c[11:18]):
        setting["bit_device"] = {
            "points": int(c[11]) if c[11] else None,
            "src": {"type": c[12], "start": c[13], "end": c[14]},
            "dst": {"type": c[15], "start": c[16], "end": c[17]},
        }

    # ワードデバイス
    if any(c[18:25]):
        setting["word_device"] = {
            "points": int(c[18]) if c[18] else None,
            "src": {"type": c[19], "start": c[20], "end": c[21]},
            "dst": {"type": c[22], "start": c[23], "end": c[24]},
        }

    return setting


# ============================================================
# CLI
# ============================================================


def _cmd_generate(args: argparse.Namespace) -> int:
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    try:
        generate_csv(config, args.out)
    except ValidationError as e:
        print("検証エラー:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 2
    print(f"OK: {args.out} を生成しました ({len(config['settings'])} 件)")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    errors = validate_config(config)
    if errors:
        print(f"NG: {len(errors)} 件のエラー", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 2
    print("OK: 設定は有効です")
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    config = parse_csv(args.csv)
    text = json.dumps(config, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"OK: {args.out} に書き出しました ({len(config['settings'])} 件)")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pg = sub.add_parser("generate", help="JSONからCSVを生成")
    pg.add_argument("config")
    pg.add_argument("out")
    pg.set_defaults(func=_cmd_generate)

    pv = sub.add_parser("validate", help="JSON設定を検証")
    pv.add_argument("config")
    pv.set_defaults(func=_cmd_validate)

    pp = sub.add_parser("parse", help="CSVからJSON設定に変換")
    pp.add_argument("csv")
    pp.add_argument("out", nargs="?")
    pp.set_defaults(func=_cmd_parse)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
