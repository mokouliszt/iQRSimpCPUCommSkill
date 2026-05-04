# melsec-iqr-simple-cpu-comm-csv

MELSEC iQ-Rシリーズ（三菱電機シーケンサ）のCPUユニット内蔵Ethernetポート部 **「シンプルCPU通信機能」** の設定CSVファイルを、生成・検証・解析する [Claude Code](https://claude.com/claude-code) 向け Skill です。

<img width="700" height="400" alt="Image" src="https://github.com/user-attachments/assets/9e7f1a16-402e-40fc-97d7-c9fc95eaab7f" />

GX Works3 が "シンプルCPU通信設定" 画面でインポート／エクスポートする UTF-16LE BOM付タブ区切りCSV を **バイト一致レベル** で生成します。

出典: **MELSEC iQ-R Ethernetユーザーズマニュアル(応用編) 1.15節 (p.220-242)**

## 姉妹 Skill との併用が前提です

このSkillは単体でも動作しますが、**シーケンサのデバイス（X / Y / M / D / T 等）の知識** に依存するため、姉妹リポジトリ [mokouliszt/iqr-device-skill](https://github.com/mokouliszt/iqr-device-skill)) と **組み合わせて使うことを前提に設計** されています。

| Skill | 役割 |
|------|------|
| [`melsec-iqr-device-overview`](https://github.com/mokouliszt/iqr-device-skill) | iQ-R デバイス全般の分類体系・命名規則・グローバル/ローカル区分・ラッチ・インデックス修飾などの**概念知識** |
| [`melsec-iqr-device-specifications`](https://github.com/mokouliszt/iqr-device-skill) | 各デバイスの**数値スペック**（点数・範囲・基数・用途） |
| `melsec-iqr-simple-cpu-comm-csv`（本リポジトリ） | 上記デバイス知識を踏まえた **シンプルCPU通信 CSV の生成・検証・解析** |

3つを同時にインストールしておくことで、Claude が「このデバイスはシンプルCPU通信で扱えるか」「点数や先頭番号の制約は満たすか」を一貫した知識で判断できるようになります。

## できること

- JSON 設定 → GX Works3 互換 CSV の生成（バイト一致）
- 既存 CSV → JSON 設定への逆変換（`parse` → 編集 → `generate` のラウンドトリップ可能）
- 生成前の網羅的バリデーション
  - 機器種別ごとのデバイス可否・範囲
  - ビット先頭16倍数 / 点数16倍数 / 1設定512ワード上限 / 全体8192ワード上限
  - SLMP のNGポート範囲（5000-5009）
  - iQ-R 固定制約（IPアドレス入力形式 = DEC 固定など）
- 機器種別 16/17/18/19/20/22/23/25/26/30 すべてに対応

詳細仕様は [skills/melsec-iqr-simple-cpu-comm-csv/SKILL.md](skills/melsec-iqr-simple-cpu-comm-csv/SKILL.md) を参照。

## インストール

Claude Code の Skill ディレクトリに、`skills/melsec-iqr-simple-cpu-comm-csv/` フォルダごとコピーします。

### グローバル（全プロジェクトで使う）

```
~/.claude/skills/melsec-iqr-simple-cpu-comm-csv/
```

### プロジェクトローカル

```
<your-project>/.claude/skills/melsec-iqr-simple-cpu-comm-csv/
```

## 使い方

### Claude Code から（推奨）

「シンプルCPU通信のCSVを作って」「この CSV を検証して」など自然言語で依頼すれば、Claude が自動的にこの Skill を呼び出します。

### CLI として直接

```bash
# JSON設定からCSVを生成（生成前に自動検証）
python skills/melsec-iqr-simple-cpu-comm-csv/scripts/generate_csv.py generate <config.json> <out.csv>

# JSONを検証のみ
python skills/melsec-iqr-simple-cpu-comm-csv/scripts/generate_csv.py validate <config.json>

# 既存CSVをJSON設定にデコード
python skills/melsec-iqr-simple-cpu-comm-csv/scripts/generate_csv.py parse <in.csv> [<out.json>]
```

最小設定例とフルパラメータ例は [skills/melsec-iqr-simple-cpu-comm-csv/examples/](skills/melsec-iqr-simple-cpu-comm-csv/examples/) を参照。

## 動作要件

- **Python 3.9 以上**（推奨は 3.10+）
- **追加依存なし**（標準ライブラリのみで完結。`pip install` 不要）

開発（テスト実行）時のみ `pytest` を使います。

## テスト

```bash
python -m pytest pytest/ -q
```

146 件のテストが、CSVフォーマット・バリデーション規則・パース／ラウンドトリップを検証します。

## ライセンス

[MIT License](LICENSE)

## 注意事項

- 本 Skill は **iQ-R 専用** です。Q / L / iQ-F / FX3 などは「交信相手」としてはサポートしますが、CSV を取り込む側のCPU（`対象ユニット`）として iQ-R 以外を想定する場合は別途調整が必要です。
- CSV をインポートするだけでは通信は開始しません。CPU 側のユニットパラメータ「シンプルCPU通信使用有無」設定や、リセット／電源OFF→ONが別途必要です（マニュアル p.221, 223 参照）。
- 三菱電機株式会社・GX Works3・MELSEC・iQ-R は三菱電機株式会社の商標です。本リポジトリは三菱電機株式会社とは関係ありません。
