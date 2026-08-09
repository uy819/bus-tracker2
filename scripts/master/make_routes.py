"""路線マスタを作成する。"""

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
        "route_name": "糸満線",
        "direction": "up",
    },

    "98_up": {
        "route_no": "98",
        "route_name": "琉大線",
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

args = parser.parse_args()


# ============================================================
# 路線確認
# ============================================================

if args.route_id not in ROUTES:
    print("エラー: 未対応のroute_idです")
    print()
    print("使用可能:")
    for route_id in ROUTES:
        print(f"  {route_id}")
    raise SystemExit(1)


config = ROUTES[args.route_id]


# ============================================================
# 出力先
# ============================================================

MASTER_DIR = (
    BASE_DIR
    / "data"
    / "routes"
    / args.route_id
    / "master"
)

MASTER_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# routes.csv
# ============================================================

routes = pd.DataFrame(
    [
        {
            "route_id": args.route_id,
            "route_no": config["route_no"],
            "route_name": config["route_name"],
            "direction": config["direction"],
        }
    ]
)


OUTPUT_FILE = MASTER_DIR / "routes.csv"

routes.to_csv(
    OUTPUT_FILE,
    index=False,
    encoding="utf-8-sig",
)


# ============================================================
# 確認
# ============================================================

print(routes.to_string(index=False))

print()
print("保存:")
print(OUTPUT_FILE)
