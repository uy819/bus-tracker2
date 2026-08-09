"""
bus_tracker.py

バスなび沖縄 リアルタイムバス停追跡

対応路線:
    89_up
    98_up
    その他、route_configに追加可能

実行:
    python scripts/tracker/bus_tracker.py --route 89_up
    python scripts/tracker/bus_tracker.py --route 98_up

テスト:
    IGNORE_TIME_CHECK=1 python scripts/tracker/bus_tracker.py --route 89_up

必要ライブラリ:
    pip install requests pandas beautifulsoup4
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests


# ============================================================
# 基本設定
# ============================================================

JST = timezone(timedelta(hours=9))

POLL_INTERVAL = 30

SCHEDULE_MATCH_MINUTES = 20

BASE_URL = "https://www.busnavi-okinawa.com/top/Location"


# ============================================================
# プロジェクトパス
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]


# ============================================================
# 路線設定
# ============================================================

ROUTES = {

    # --------------------------------------------------------
    # 89番 糸満線 上り
    # --------------------------------------------------------

    "89_up": {

        "route_no": "89",

        "route_name": "89番 糸満線",

        "direction": "up",

        "direction_name": "上り",

        "keitou_sid":
            "f05ce44e-f2f9-4686-90b4-ff244e1c5813",

        "course_group_sid":
            "37e827b7-aab1-4971-afa2-7e3d915e722d",

        "course_sid":
            "AllStations",

        "course_name":
            "全停留所表示",

    },


    # --------------------------------------------------------
    # 98番 琉大線 上り
    #
    # 現在はSID未設定
    # 98番のバスなび沖縄ページから取得して設定する
    # --------------------------------------------------------

    "98_up": {

        "route_no": "98",

        "route_name": "98番 琉大線",

        "direction": "up",

        "direction_name": "上り",

        "keitou_sid":
            "ed0ad81d-cd34-43c8-95a9-b8a88cad67a7",

        "course_group_sid":
            "a57af64c-6c6f-439e-951c-46fb5ef4f804",

        "course_sid":
            "AllStations",

        "course_name":
            "全停留所表示",

    },

}


# ============================================================
# HTTP設定
# ============================================================

HEADERS = {

    "Referer":
        "https://www.busnavi-okinawa.com/top/Location",

    "User-Agent":
        (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),

    "X-Requested-With":
        "XMLHttpRequest",

}


# ============================================================
# 引数
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description="バスなび沖縄 リアルタイムバス停追跡"
    )

    parser.add_argument(
        "--route",
        required=True,
        choices=ROUTES.keys(),
        help="追跡する路線ID",
    )

    return parser.parse_args()


# ============================================================
# 路線設定取得
# ============================================================

def get_route_config(route_id):

    if route_id not in ROUTES:

        raise ValueError(
            f"未登録の路線です: {route_id}"
        )

    config = ROUTES[route_id]

    if not config["keitou_sid"]:

        raise ValueError(
            f"{route_id} の keitouSid が未設定です"
        )

    if not config["course_group_sid"]:

        raise ValueError(
            f"{route_id} の courseGroupSid が未設定です"
        )

    return config


# ============================================================
# パス生成
# ============================================================

def get_paths(route_id):

    route_dir = (
        BASE_DIR
        / "data"
        / "routes"
        / route_id
    )

    master_dir = (
        route_dir
        / "master"
    )

    raw_dir = (
        BASE_DIR
        / "data"
        / "raw"
        / route_id
    )

    raw_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    processed_dir = (
        BASE_DIR
        / "data"
        / "processed"
    )

    processed_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return {

        "route_dir":
            route_dir,

        "stop_times":
            master_dir
            / "stop_times.csv",

        "arrival_log":
            raw_dir
            / "bus_arrival_log.csv",

        "live_json":
            raw_dir
            / "bus_live_position.json",

    }


# ============================================================
# 時刻変換
# ============================================================

def time_to_seconds(value):

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    try:

        parts = text.split(":")

        if len(parts) != 2:
            return None

        hour = int(parts[0])
        minute = int(parts[1])

        return (
            hour * 3600
            + minute * 60
        )

    except Exception:

        return None


# ============================================================
# StopTimes読込
# ============================================================

def load_stop_times(stop_times_file):

    if not stop_times_file.exists():

        raise FileNotFoundError(
            f"stop_times.csv がありません:\n"
            f"{stop_times_file}"
        )

    stop_times = pd.read_csv(
        stop_times_file,
        encoding="utf-8-sig",
    )

    required = [
        "trip_id",
        "trip_no",
        "route_id",
        "direction",
        "stop_id",
        "stop_name",
        "stop_order",
        "scheduled_time",
    ]

    missing = [
        col
        for col in required
        if col not in stop_times.columns
    ]

    if missing:

        raise ValueError(
            "stop_times.csv に必要な列がありません: "
            + ", ".join(missing)
        )

    stop_times["scheduled_sec"] = (
        stop_times["scheduled_time"]
        .apply(time_to_seconds)
    )

    stop_times = stop_times.dropna(
        subset=["scheduled_sec"]
    ).copy()

    stop_times["scheduled_sec"] = (
        stop_times["scheduled_sec"]
        .astype(int)
    )

    stop_times["stop_order"] = (
        pd.to_numeric(
            stop_times["stop_order"],
            errors="coerce",
        )
    )

    return stop_times


# ============================================================
# StopTimesから時刻表を作成
# ============================================================

def build_timetable(stop_times):

    timetable = {}

    for stop_name, group in stop_times.groupby(
        "stop_name"
    ):

        times = (
            group["scheduled_time"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        timetable[stop_name] = sorted(
            times,
            key=lambda x: time_to_seconds(x)
            if time_to_seconds(x) is not None
            else 999999
        )

    return timetable


# ============================================================
# 路線の始発・終点停留所
# ============================================================

def get_route_stops(stop_times):

    stops = (
        stop_times[
            [
                "stop_id",
                "stop_name",
                "stop_order",
            ]
        ]
        .drop_duplicates()
        .sort_values("stop_order")
    )

    return stops.reset_index(drop=True)


# ============================================================
# APIパラメータ
# ============================================================

def build_api_params(config):

    return {

        "datetime":
            "28",

        "keitouSid":
            config["keitou_sid"],

        "courseGroupSid":
            config["course_group_sid"],

        "courseSid":
            config["course_sid"],

        "courseName":
            config["course_name"],

    }


# ============================================================
# APIリクエスト
# ============================================================

def fetch_with_retry(
    url,
    params,
    retries=3,
    timeout=30,
):

    for attempt in range(
        1,
        retries + 1,
    ):

        try:

            p = {
                **params,
                "_":
                    int(
                        time.time()
                        * 1000
                    ),
            }

            response = requests.get(
                url,
                params=p,
                headers=HEADERS,
                timeout=timeout,
            )

            response.raise_for_status()

            return response

        except Exception as e:

            print(
                f"\n  ⚠ 取得失敗 "
                f"({attempt}/{retries}): {e}"
            )

            if attempt < retries:

                time.sleep(
                    5 * attempt
                )

    return None


# ============================================================
# BusStateTable
# ============================================================

def fetch_bus_state_table(api_params):

    response = fetch_with_retry(
        f"{BASE_URL}/BusStateTable",
        api_params,
    )

    if response is None:
        return None

    try:

        html = response.json()

        if not isinstance(
            html,
            str,
        ):

            html = response.text

    except Exception:

        html = response.text

    result = {}

    last_name = None
    last_sid = None

    dt_positions = [
        m.start()
        for m in re.finditer(
            r'<dt(?:\s+class="iconBusDT")?>',
            html,
        )
    ]

    segments = []

    for i, pos in enumerate(
        dt_positions
    ):

        if (
            i + 1
            < len(dt_positions)
        ):

            end = dt_positions[i + 1]

        else:

            end = len(html)

        segments.append(
            html[pos:end]
        )

    for seg in segments:

        num_match = re.match(
            r'<dt(?:\s+class="iconBusDT")?>(\d*)</dt>',
            seg,
        )

        num = (
            num_match.group(1)
            if num_match
            else ""
        )

        has_bus = (
            "icon_bus" in seg
        )

        # ----------------------------------------------------
        # 通常のバス停
        # ----------------------------------------------------

        if num != "":

            name_match = re.search(
                r'busstopClickPopUpInfo\(\d+\);?"\s*>([^<]+)</a>',
                seg,
            )

            sid_match = re.search(
                r"getStationNo\(['\"]([^'\"]+)['\"]\)",
                seg,
            )

            if (
                name_match
                and sid_match
            ):

                last_name = (
                    name_match
                    .group(1)
                    .strip()
                )

                last_sid = (
                    sid_match
                    .group(1)
                )

            else:

                last_name = (
                    f"停留所#{num}"
                    "（名称取得失敗）"
                )

                last_sid = (
                    f"unknown-{num}"
                )

            result[last_sid] = {

                "name":
                    last_name,

                "has_bus":
                    has_bus,

            }

        # ----------------------------------------------------
        # 移動中のバス
        # ----------------------------------------------------

        else:

            if (
                has_bus
                and last_sid
            ):

                result[last_sid] = {

                    "name":
                        last_name,

                    "has_bus":
                        True,

                }

    return result


# ============================================================
# BusLocation
# ============================================================

def fetch_bus_location(api_params):

    response = fetch_with_retry(
        f"{BASE_URL}/BusLocation",
        api_params,
    )

    if response is None:
        return None

    try:

        return response.json()

    except Exception:

        return None


# ============================================================
# 最寄り定刻
# ============================================================

def get_nearest_schedule(
    stop_name,
    now_hhmm,
    timetable,
):

    if not stop_name:

        return "", None

    # --------------------------------------------------------
    # 完全一致
    # --------------------------------------------------------

    times = timetable.get(
        stop_name,
        [],
    )

    # --------------------------------------------------------
    # 部分一致
    # --------------------------------------------------------

    if not times:

        for key, values in timetable.items():

            if (
                key in stop_name
                or stop_name in key
            ):

                times = values

                break

    if not times:

        return "", None

    now_sec = time_to_seconds(
        now_hhmm
    )

    if now_sec is None:

        return "", None

    best_sched = ""

    best_delay = None

    best_abs = float("inf")

    for sched in times:

        sched_sec = time_to_seconds(
            sched
        )

        if sched_sec is None:
            continue

        diff_min = int(
            (
                now_sec
                - sched_sec
            )
            / 60
        )

        if (
            -5
            <= diff_min
            <= SCHEDULE_MATCH_MINUTES
        ):

            if (
                abs(diff_min)
                < best_abs
            ):

                best_abs = abs(
                    diff_min
                )

                best_sched = sched

                best_delay = (
                    diff_min
                )

    return (
        best_sched,
        best_delay,
    )


# ============================================================
# 状況判定
# ============================================================

def judge_status(delay):

    if delay is None:

        return "定刻不明"

    if (
        -1
        <= delay
        <= 3
    ):

        return "定時"

    if delay > 3:

        return (
            f"遅延 +{delay}分"
        )

    return (
        f"早着 {delay}分"
    )


# ============================================================
# 距離計算
# ============================================================

def calculate_distance(
    lat1,
    lon1,
    lat2,
    lon2,
):

    try:

        lat1 = float(lat1)
        lon1 = float(lon1)

        lat2 = float(lat2)
        lon2 = float(lon2)

    except Exception:

        return float("inf")

    R = 6371000

    p1 = math.radians(lat1)

    p2 = math.radians(lat2)

    dp = math.radians(
        lat2 - lat1
    )

    dl = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(dp / 2) ** 2
        +
        math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return (
        R
        * 2
        * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a),
        )
    )


# ============================================================
# バス停に最も近い車両
# ============================================================

def match_bus_to_stop(
    buses,
    stop_lat,
    stop_lon,
):

    if (
        not buses
        or not stop_lat
        or not stop_lon
    ):

        return "", ""

    best_distance = float(
        "inf"
    )

    best_plate = ""

    best_company = ""

    for bus_data in buses:

        position = bus_data.get(
            "Position",
            {},
        )

        lat = position.get(
            "Latitude"
        )

        lon = position.get(
            "Longitude"
        )

        if not lat or not lon:
            continue

        distance = (
            calculate_distance(
                stop_lat,
                stop_lon,
                lat,
                lon,
            )
        )

        if (
            distance
            < best_distance
        ):

            best_distance = distance

            bus = bus_data.get(
                "Bus",
                {},
            )

            best_plate = (
                bus.get(
                    "NumberPlate",
                    "",
                )
            )

            company = bus.get(
                "Company",
                {},
            )

            best_company = (
                company.get(
                    "Name",
                    "",
                )
            )

    return (
        best_plate,
        best_company,
    )


# ============================================================
# バス停座標取得
# ============================================================

def fetch_station_coords(
    api_params
):

    station_coords = {}

    try:

        params = {
            **api_params,
            "_":
                int(
                    time.time()
                    * 1000
                ),
        }

        response = requests.get(
            f"{BASE_URL}/GetStations",
            params=params,
            headers=HEADERS,
            timeout=30,
        )

        response.raise_for_status()

        stations = response.json()

        for station in stations:

            sid = station.get(
                "Sid",
                "",
            )

            position = station.get(
                "Position",
                {},
            )

            station_coords[sid] = {

                "lat":
                    position.get(
                        "Latitude"
                    ),

                "lon":
                    position.get(
                        "Longitude"
                    ),

            }

        print(
            f"  {len(station_coords)}件取得"
        )

    except Exception as e:

        print(
            f"  取得失敗: {e}"
        )

    return station_coords


# ============================================================
# 到着ログ保存
# ============================================================

def save_record(
    output_csv,
    record,
):

    output_csv.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    exists = (
        output_csv.exists()
    )

    fieldnames = [

        "日付",
        "到着時刻",
        "定刻",
        "遅延(分)",
        "状況",
        "系統",
        "バス停名",
        "ナンバー",
        "バス会社",

    ]

    with open(
        output_csv,
        "a",
        newline="",
        encoding="utf-8-sig",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        if not exists:

            writer.writeheader()

        writer.writerow(record)

    print(
        f"  💾 "
        f"{record['バス停名'][:15]:15s} "
        f"着:{record['到着時刻']} "
        f"定刻:{record['定刻'] or '-----':5s} "
        f"[{record['状況']}]"
    )


# ============================================================
# リアルタイム位置保存
# ============================================================

def save_live_positions(
    live_json,
    buses,
    now,
    config,
):

    items = []

    if buses:

        for bus_data in buses:

            position = bus_data.get(
                "Position",
                {},
            )

            bus = bus_data.get(
                "Bus",
                {},
            )

            lat = position.get(
                "Latitude"
            )

            lon = position.get(
                "Longitude"
            )

            if (
                not lat
                or not lon
            ):

                continue

            items.append({

                "lat":
                    lat,

                "lon":
                    lon,

                "plate":
                    bus.get(
                        "NumberPlate",
                        "",
                    ),

                "company":
                    bus.get(
                        "Company",
                        {}
                    ).get(
                        "Name",
                        "",
                    ),

            })

    payload = {

        "updated_at":
            now.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "route_id":
            config["route_no"],

        "route":
            config["route_name"],

        "direction":
            config["direction"],

        "buses":
            items,

    }

    live_json.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        live_json,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# Git push
# ============================================================

def push_live_files(
    live_json,
    arrival_csv,
):

    try:

        subprocess.run(
            [
                "git",
                "config",
                "user.name",
                "github-actions[bot]",
            ],
            check=False,
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "github-actions[bot]@users.noreply.github.com",
            ],
            check=False,
        )

        subprocess.run(
            [
                "git",
                "add",
                str(live_json),
                str(arrival_csv),
            ],
            check=False,
        )

        result = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
            ],
            check=False,
        )

        if result.returncode == 0:

            return

        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "live update",
                "--quiet",
            ],
            check=False,
        )

        pull = subprocess.run(
            [
                "git",
                "pull",
                "--rebase",
                "--quiet",
                "origin",
                "main",
            ],
            check=False,
        )

        if pull.returncode != 0:

            subprocess.run(
                [
                    "git",
                    "rebase",
                    "--abort",
                ],
                check=False,
            )

            print(
                "  ⚠ pull --rebase "
                "失敗のためpushをスキップ"
            )

            return

        subprocess.run(
            [
                "git",
                "push",
                "--quiet",
            ],
            check=False,
        )

    except Exception as e:

        print(
            f"  ⚠ push失敗: {e}"
        )


# ============================================================
# メイン
# ============================================================

def main():

    args = parse_args()

    route_id = args.route

    config = get_route_config(
        route_id
    )

    paths = get_paths(
        route_id
    )

    # --------------------------------------------------------
    # StopTimes
    # --------------------------------------------------------

    stop_times = load_stop_times(
        paths["stop_times"]
    )

    timetable = build_timetable(
        stop_times
    )

    route_stops = get_route_stops(
        stop_times
    )

    # --------------------------------------------------------
    # API
    # --------------------------------------------------------

    api_params = build_api_params(
        config
    )

    # --------------------------------------------------------
    # 表示
    # --------------------------------------------------------

    print(
        "=" * 60
    )

    print(
        f"  バスなび沖縄 "
        f"{config['route_name']} "
        f"（{config['direction_name']}）"
    )

    print(
        "=" * 60
    )

    print(
        f"  route_id     : {route_id}"
    )

    print(
        f"  route_no     : "
        f"{config['route_no']}"
    )

    print(
        f"  停留所数     : "
        f"{len(route_stops)}"
    )

    print(
        f"  便数         : "
        f"{stop_times['trip_id'].nunique()}"
    )

    print(
        f"  更新間隔     : "
        f"{POLL_INTERVAL}秒"
    )

    print(
        f"  到着ログ     : "
        f"{paths['arrival_log']}"
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # バス停座標
    # --------------------------------------------------------

    print(
        "\nバス停座標を取得中..."
    )

    station_coords = (
        fetch_station_coords(
            api_params
        )
    )

    # --------------------------------------------------------
    # 監視
    # --------------------------------------------------------

    print(
        "\n監視開始"
    )

    print(
        "Ctrl+C で停止\n"
    )

    prev_state = {}

    count = 0

    ignore_time_check = (
        os.environ.get(
            "IGNORE_TIME_CHECK",
            "0",
        )
        == "1"
    )

    while True:

        count += 1

        now = datetime.now(
            JST
        )

        # ----------------------------------------------------
        # 時間帯
        # ----------------------------------------------------

        if (
            not ignore_time_check
            and now.hour >= 9
        ):

            print(
                f"[{now.strftime('%H:%M:%S')}] "
                "監視時間終了（9時）"
            )

            break

        if (
            not ignore_time_check
            and now.hour < 7
        ):

            print(
                f"[{now.strftime('%H:%M:%S')}] "
                "監視時間前 — 60秒待機"
            )

            time.sleep(60)

            continue

        # ----------------------------------------------------
        # API取得
        # ----------------------------------------------------

        print(
            f"[#{count}] "
            f"{now.strftime('%H:%M:%S')} "
            "取得中...",
            end=" ",
            flush=True,
        )

        state = fetch_bus_state_table(
            api_params
        )

        if state is None:

            print(
                "取得失敗"
            )

            time.sleep(
                POLL_INTERVAL
            )

            continue

        buses = fetch_bus_location(
            api_params
        )

        # ----------------------------------------------------
        # live position
        # ----------------------------------------------------

        save_live_positions(
            paths["live_json"],
            buses,
            now,
            config,
        )

        # ----------------------------------------------------
        # 3回に1回push
        # ----------------------------------------------------

        if count % 3 == 0:

            push_live_files(
                paths["live_json"],
                paths["arrival_log"],
            )

        active = [

            value["name"]

            for value in state.values()

            if value["has_bus"]

        ]

        print(
            f"バスあり "
            f"{len(active)}停留所"
        )

        # ----------------------------------------------------
        # 到着判定
        # ----------------------------------------------------

        for sid, info in state.items():

            was_there = (
                prev_state.get(
                    sid,
                    False,
                )
            )

            is_there = (
                info["has_bus"]
            )

            # ------------------------------------------------
            # 到着
            # ------------------------------------------------

            if (
                is_there
                and not was_there
            ):

                now_hhmm = (
                    now.strftime(
                        "%H:%M"
                    )
                )

                stop_name = (
                    info["name"]
                )

                sched, delay = (
                    get_nearest_schedule(
                        stop_name,
                        now_hhmm,
                        timetable,
                    )
                )

                status = (
                    judge_status(
                        delay
                    )
                )

                coords = (
                    station_coords.get(
                        sid,
                        {},
                    )
                )

                plate, company = (
                    match_bus_to_stop(
                        buses,
                        coords.get(
                            "lat"
                        ),
                        coords.get(
                            "lon"
                        ),
                    )
                )

                record = {

                    "日付":
                        now.strftime(
                            "%Y/%m/%d"
                        ),

                    "到着時刻":
                        now_hhmm,

                    "定刻":
                        sched,

                    "遅延(分)":
                        delay
                        if delay is not None
                        else "",

                    "状況":
                        status,

                    "系統":
                        config["route_no"],

                    "バス停名":
                        stop_name,

                    "ナンバー":
                        plate,

                    "バス会社":
                        company,

                }

                print(
                    f"\n  🚌 到着: "
                    f"{stop_name}"
                )

                save_record(
                    paths["arrival_log"],
                    record,
                )

            # ------------------------------------------------
            # 離脱
            # ------------------------------------------------

            elif (
                not is_there
                and was_there
            ):

                print(
                    f"  → 離脱: "
                    f"{info['name']}"
                )

        # ----------------------------------------------------
        # 状態更新
        # ----------------------------------------------------

        prev_state = {

            sid:
                value["has_bus"]

            for sid, value
            in state.items()

        }

        time.sleep(
            POLL_INTERVAL
        )


# ============================================================
# 実行
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n\n監視を停止しました。"
        )

    except Exception as e:

        print(
            "\n\nエラー:"
        )

        print(e)

        raise
