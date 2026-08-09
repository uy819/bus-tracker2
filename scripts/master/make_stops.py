"""時刻表行列から stops.csv を作成する。"""

from argparse import ArgumentParser
from pathlib import Path

import pandas as pd


# ============================================================
# パス
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]


# ============================================================
# 路線設定
# ============================================================

ROUTES = {
    "89_up": {
        "route_no": "89",
    },

    "98_up": {
        "route_no": "98",
    },
}


# ============================================================
# 引数
# ============================================================

parser = ArgumentParser()

parser.add_argument(
    "--route-id",
    required=True,
    help="路線ID 例: 89_up / 98_up",
)

args = parser.parse_args()


# ============================================================
# 路線確認
# ============================================================

if args.route_id not in ROUTES:
    print("エラー: 未対応のroute_idです")
    print()

    print("使用可能なroute_id:")
    for route_id in ROUTES:
        print(f"  {route_id}")

    raise SystemExit(1)


route_no = ROUTES[args.route_id]["route_no"]


# ============================================================
# ファイル
# ============================================================

matrix_file = (
    BASE_DIR
    / "data"
    / "processed"
    / f"{args.route_id}_timetable_matrix.csv"
)

output_file = (
    BASE_DIR
    / "data"
    / "routes"
    / args.route_id
    / "master"
    / "stops.csv"
)


# ============================================================
# 入力確認
# ============================================================

if not matrix_file.exists():
    raise FileNotFoundError(
        f"\n時刻表行列がありません:\n{matrix_file}\n\n"
        f"先に {args.route_id}_timetable_matrix.csv を作成してください。"
    )


print("loading...")
print()
print("route_id:", args.route_id)
print("route_no:", route_no)
print()
print("入力:")
print(matrix_file)


# ============================================================
# 時刻表読込
# ============================================================

matrix = pd.read_csv(
    matrix_file,
    encoding="utf-8-sig",
    dtype=str,
)


# ============================================================
# stop_name確認
# ============================================================

if "stop_name" not in matrix.columns:
    raise ValueError(
        "timetable_matrix.csv に stop_name 列がありません。"
    )


names = (
    matrix["stop_name"]
    .fillna("")
    .str.strip()
)


if (names == "").any():

    empty_rows = (
        matrix.index[names == ""]
        .tolist()
    )

    raise ValueError(
        "stop_name に空値があります。\n"
        f"該当行: {empty_rows}"
    )


# ============================================================
# 重複確認
# ============================================================

duplicate_names = (
    names[names.duplicated(keep=False)]
    .unique()
    .tolist()
)


if duplicate_names:

    print()
    print("警告:")
    print("同名停留所があります。")
    print()

    for name in duplicate_names:
        print(f"  {name}")

    print()
    print(
        "同名停留所が複数回登場する路線では、"
        "stop_order を使って区別します。"
    )


# ============================================================
# stops.csv 作成
# ============================================================

stops = pd.DataFrame(
    {
        "stop_id": [
            f"{route_no}{i:03d}"
            for i in range(1, len(names) + 1)
        ],

        "stop_order": range(
            1,
            len(names) + 1,
        ),

        "stop_name": names,
    }
)


# ============================================================
# 出力
# ============================================================

output_file.parent.mkdir(
    parents=True,
    exist_ok=True,
)


stops.to_csv(
    output_file,
    index=False,
    encoding="utf-8-sig",
)


# ============================================================
# 確認
# ============================================================

print()
print("======================")
print("stops.csv 作成完了")
print("======================")

print()

print("路線:")
print(args.route_id)

print()

print("路線番号:")
print(route_no)

print()

print("停留所数:")
print(len(stops))

print()

print("先頭:")
print(
    stops.head(10).to_string(index=False)
)

print()

print("末尾:")
print(
    stops.tail(5).to_string(index=False)
)

print()

print("保存先:")
print(output_file)
