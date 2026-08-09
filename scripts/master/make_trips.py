"""時刻表行列の各便列から trips.csv を作成する。"""

from argparse import ArgumentParser
from pathlib import Path
import sys

import pandas as pd


# ============================================================
# パス設定
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

sys.path.append(
    str(BASE_DIR / "scripts")
)

from utils import normalize_time


# ============================================================
# 路線設定
# ============================================================

ROUTES = {
    "89_up": {
        "direction": "up",
    },

    "98_up": {
        "direction": "up",
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

parser.add_argument(
    "--direction",
    default=None,
    help="方向。指定しなければ路線設定から取得",
)

args = parser.parse_args()


# ============================================================
# 路線確認
# ============================================================

if args.route_id not in ROUTES:

    print()
    print("エラー: 未対応のroute_idです")
    print()

    print("使用可能なroute_id:")

    for route_id in ROUTES:
        print(f"  {route_id}")

    raise SystemExit(1)


direction = (
    args.direction
    if args.direction is not None
    else ROUTES[args.route_id]["direction"]
)


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
    / "trips.csv"
)


# ============================================================
# 入力確認
# ============================================================

if not matrix_file.exists():

    raise FileNotFoundError(
        f"\n時刻表行列がありません:\n"
        f"{matrix_file}\n\n"
        f"先に {args.route_id}_timetable_matrix.csv "
        f"を作成してください。"
    )


print("loading...")
print()

print("route_id:")
print(args.route_id)

print()

print("direction:")
print(direction)

print()

print("入力:")
print(matrix_file)


# ============================================================
# 時刻表読込
# ============================================================

matrix = pd.read_csv(
    matrix_file,
    encoding="utf-8-sig",
)


# ============================================================
# 基本チェック
# ============================================================

if matrix.empty:
    raise ValueError(
        "時刻表行列が空です。"
    )


if "stop_name" not in matrix.columns:

    raise ValueError(
        "timetable_matrix.csv に "
        "'stop_name' 列がありません。"
    )


# ============================================================
# 始発停留所
# ============================================================

first_stop = matrix.iloc[0]

first_stop_name = str(
    first_stop["stop_name"]
).strip()


if not first_stop_name:

    raise ValueError(
        "始発停留所の stop_name が空です。"
    )


print()

print("始発停留所:")
print(first_stop_name)


# ============================================================
# 便列判定
# ============================================================

"""
timetable_matrix.csv の想定構造:

stop_id
stop_name
stop_order
col_3
col_4
col_5
...

3列目以降が便列。

make_trips.py では各便列の
「始発停留所」の時刻を取得して、
有効な時刻が存在する列だけを便として登録する。
"""


if len(matrix.columns) <= 3:

    raise ValueError(
        "便列が存在しません。"
    )


rows = []


for column_index, column_name in enumerate(
    matrix.columns[3:],
    start=3,
):

    value = first_stop[column_name]

    start_time = normalize_time(
        value
    )

    # --------------------------------------------
    # 空欄・無効時刻
    # --------------------------------------------

    if start_time is None:
        continue


    # --------------------------------------------
    # 便番号
    # --------------------------------------------

    trip_no = len(rows) + 1


    # --------------------------------------------
    # trip_id
    #
    # 例:
    # 98_up_001
    # 98_up_002
    # --------------------------------------------

    trip_id = (
        f"{args.route_id}_{trip_no:03d}"
    )


    rows.append(
        {
            "column_index": column_index,

            "column_name": column_name,

            "trip_no": trip_no,

            "trip_id": trip_id,

            "route_id": args.route_id,

            "direction": direction,

            "start_time": start_time,
        }
    )


# ============================================================
# DataFrame
# ============================================================

trips = pd.DataFrame(
    rows,
    columns=[
        "column_index",
        "column_name",
        "trip_no",
        "trip_id",
        "route_id",
        "direction",
        "start_time",
    ],
)


# ============================================================
# 便がない場合
# ============================================================

if trips.empty:

    raise ValueError(
        "始発停留所から有効な便時刻を取得できませんでした。\n"
        f"始発停留所: {first_stop_name}"
    )


# ============================================================
# start_time順に並べる
# ============================================================

trips = trips.sort_values(
    [
        "start_time",
        "trip_no",
    ]
).reset_index(
    drop=True
)


# ============================================================
# trip_no再採番
# ============================================================

trips["trip_no"] = (
    range(
        1,
        len(trips) + 1
    )
)


# trip_idを再生成
trips["trip_id"] = trips["trip_no"].apply(
    lambda n: f"{args.route_id}_{n:03d}"
)


# ============================================================
# 保存
# ============================================================

output_file.parent.mkdir(
    parents=True,
    exist_ok=True,
)


trips.to_csv(
    output_file,
    index=False,
    encoding="utf-8-sig",
)


# ============================================================
# 結果表示
# ============================================================

print()
print("======================")
print("trips.csv 作成完了")
print("======================")

print()

print("路線:")
print(args.route_id)

print()

print("方向:")
print(direction)

print()

print("始発停留所:")
print(first_stop_name)

print()

print("便数:")
print(len(trips))

print()

print("便一覧:")
print(
    trips[
        [
            "trip_no",
            "trip_id",
            "start_time",
        ]
    ].to_string(index=False)
)

print()

print("保存先:")
print(output_file)
