# scripts/check_api_detail.py
"""
BoatraceAPIClient の動作確認。
実際にパースしてRaceProgramとRaceResultが正しく生成されるか確認する。
"""

import sys
import os
import logging
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level="INFO",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from src.data.boatrace_api import BoatraceAPIClient

def main():
    client = BoatraceAPIClient(cache_dir=Path("data/raw"))
    yesterday = client.yesterday()

    print("\n=== 昨日({})の結果：大村(24番) ===".format(yesterday))
    results = client.get_venue_results(yesterday, stadium_number=24)
    if results:
        for r in results[:3]:   # 最初の3レース分表示
            print(
                "  {}R  {}  {}円  決まり手:{}".format(
                    r.race_number,
                    r.trifecta_combination,
                    r.trifecta_amount,
                    r.technique,
                )
            )
    else:
        print("  → データなし（昨日は大村開催なし）")

    print("\n=== 昨日({})の出走表：桐生(1番) ===".format(yesterday))
    races = client.get_venue_races(yesterday, stadium_number=1)
    if races:
        r0 = races[0]
        print(
            "  {}R  {}  {}  {}m".format(
                r0.race_number, r0.venue_name,
                r0.grade_label, r0.distance
            )
        )
        print(
            "  天候: {} 風:{}{} m/s 波:{}cm".format(
                r0.weather.weather,
                r0.weather.wind_direction,
                r0.weather.wind_speed,
                r0.weather.wave_height,
            )
        )
        for e in r0.entries:
            print(
                "  {}号艇 {} ({}) 勝率:{} モーター2連率:{}%".format(
                    e.boat_number,
                    e.racer.name,
                    e.racer.grade,
                    e.racer.national_win_rate,
                    e.motor_boat.motor_in2_rate,
                )
            )
    else:
        print("  → データなし")

    print("\n=== 直前情報：今日({}) ===".format(client.today()))
    previews = client.fetch_previews(client.today())
    if previews:
        first_key = list(previews.keys())[0]
        exh_list  = previews[first_key]
        print("  キー例: {}".format(first_key))
        for exh in exh_list:
            print(
                "  {}号艇  コース:{} 展示タイム:{} ST:{}".format(
                    exh.boat_number,
                    exh.course_number,
                    exh.exhibition_time,
                    exh.start_timing,
                )
            )
    else:
        print("  → データなし")

if __name__ == "__main__":
    main()
