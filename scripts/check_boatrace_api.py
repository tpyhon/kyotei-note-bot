# scripts/check_boatrace_api.py
"""
BoatraceOpenAPI の実際のレスポンス構造を確認するスクリプト。
キー名の確認・パース動作の検証に使う。

使い方:
    python scripts/check_boatrace_api.py
"""

import sys
import os
import json
import logging
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level="INFO",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("check_api")

import requests

BASE = "https://boatraceopenapi.github.io"

def fetch(url: str) -> dict | None:
    resp = requests.get(url, timeout=20)
    logger.info(f"GET {url} → {resp.status_code}")
    if resp.status_code == 200:
        return resp.json()
    return None


def main():
    today     = date.today()
    yesterday = today - timedelta(days=1)

    print("\n" + "=" * 60)
    print("① 今日の出走表（programs）- トップレベルキーを確認")
    print("=" * 60)
    url = f"{BASE}/programs/v3/{today.year}/{today.strftime('%Y%m%d')}.json"
    data = fetch(url)
    if data:
        print(f"  トップレベルキー: {list(data.keys())}")
        races = data.get("races") or data.get("race_list") or []
        if not races:
            # どのキーにレースが入っているか全部表示
            for k, v in data.items():
                print(f"  [{k}] type={type(v).__name__}, ", end="")
                if isinstance(v, list):
                    print(f"len={len(v)}")
                elif isinstance(v, dict):
                    print(f"keys={list(v.keys())[:5]}")
                else:
                    print(f"value={str(v)[:50]}")
        else:
            print(f"  レース数: {len(races)}")
            # 最初の1レースのキーを表示
            if races:
                r0 = races[0]
                print(f"\n  races[0] のキー: {list(r0.keys())}")
                # 選手情報のキーも確認
                players = (
                    r0.get("players") or
                    r0.get("player_list") or
                    r0.get("entries") or []
                )
                if players:
                    p0 = players[0]
                    print(f"  players[0] のキー: {list(p0.keys())}")
                    print(f"\n  players[0] の中身（全フィールド）:")
                    print(json.dumps(p0, ensure_ascii=False, indent=4))
                print(f"\n  races[0] の中身（players以外）:")
                r0_no_players = {
                    k: v for k, v in r0.items()
                    if k not in ("players", "player_list", "entries")
                }
                print(json.dumps(r0_no_players, ensure_ascii=False, indent=4))
    else:
        print("  → データなし（本日開催なし or まだ未公開）")

    print("\n" + "=" * 60)
    print("② 昨日の結果（results）- トップレベルキーを確認")
    print("=" * 60)
    url = f"{BASE}/results/v3/{yesterday.year}/{yesterday.strftime('%Y%m%d')}.json"
    data = fetch(url)
    if data:
        print(f"  トップレベルキー: {list(data.keys())}")
        races = data.get("races") or data.get("race_list") or []
        if races:
            r0 = races[0]
            print(f"  races[0] のキー: {list(r0.keys())}")
            print(f"\n  races[0] の中身:")
            print(json.dumps(r0, ensure_ascii=False, indent=4))
    else:
        print("  → データなし")

    print("\n" + "=" * 60)
    print("③ 直前情報（previews）- トップレベルキーを確認")
    print("=" * 60)
    url = f"{BASE}/previews/v3/{today.year}/{today.strftime('%Y%m%d')}.json"
    data = fetch(url)
    if data:
        print(f"  トップレベルキー: {list(data.keys())}")
        races = data.get("races") or data.get("race_list") or []
        if races:
            r0 = races[0]
            print(f"  races[0] のキー: {list(r0.keys())}")
            print(f"\n  races[0] の中身:")
            print(json.dumps(r0, ensure_ascii=False, indent=4))
    else:
        print("  → データなし（レース前は未公開）")


if __name__ == "__main__":
    main()
