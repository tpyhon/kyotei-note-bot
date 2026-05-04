# src/data/boatrace_api.py
"""
BoatraceOpenAPI クライアント（実際のキー名確定版）

確認済み仕様:
  - トップレベルキー: programs / results / previews
  - 場番号: stadium_number（整数、1〜24）
  - 艇情報: boats[]（programs/results）または boats{}（previews、艇番をキーとする辞書）
  - 払戻: payouts.trifecta[0].combination / .amount
"""

import json
import logging
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

from src.data.models import (
    RaceProgram,
    RaceResult,
    RaceEntry,
    RacerProfile,
    MotorBoat,
    WeatherInfo,
    ExhibitionInfo,
    VenueConfig,
    STADIUM_MAP,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# ──────────────────────────────────────────
# エンドポイント URL 生成
# ──────────────────────────────────────────

_BASE = "https://boatraceopenapi.github.io"

def _url(data_type: str, dt: date) -> str:
    return "{}/{}/v3/{}/{}.json".format(
        _BASE, data_type, dt.year, dt.strftime("%Y%m%d")
    )


# ──────────────────────────────────────────
# BoatraceAPIClient
# ──────────────────────────────────────────

class BoatraceAPIClient:
    """
    BoatraceOpenAPI からデータを取得するクライアント。

    使い方:
        client = BoatraceAPIClient(cache_dir=Path("data/raw"))

        # 特定場（大村=24番）の今日の全レース取得
        races = client.get_venue_races(client.today(), stadium_number=24)

        # 昨日の結果を取得
        results = client.get_venue_results(client.yesterday(), stadium_number=24)
    """

    _RETRY_COUNT = 3
    _RETRY_WAIT  = 2.0

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir
        self.session   = requests.Session()
        self.session.headers.update({"User-Agent": "kyotei-note-bot/1.0"})

    # ──────────────────────────────────────
    # 公開メソッド：日付ユーティリティ
    # ──────────────────────────────────────

    def today(self) -> date:
        return datetime.now(JST).date()

    def yesterday(self) -> date:
        return self.today() - timedelta(days=1)

    # ──────────────────────────────────────
    # 公開メソッド：全場取得
    # ──────────────────────────────────────

    def fetch_programs(self, dt: date) -> list[RaceProgram]:
        """指定日の全場・全レースの出走表を取得する。"""
        raw = self._fetch_json("programs", dt)
        if not raw:
            return []
        return self._parse_programs(raw, dt)

    def fetch_results(self, dt: date) -> list[RaceResult]:
        """指定日の全場・全レースの結果を取得する。"""
        raw = self._fetch_json("results", dt)
        if not raw:
            return []
        return self._parse_results(raw, dt)

    def fetch_previews(self, dt: date) -> dict[str, list[ExhibitionInfo]]:
        """
        指定日の直前情報を取得する。

        Returns:
            キー "{stadium_number}_{race_number}" → ExhibitionInfo リスト
            例: "24_8" = 大村8R
        """
        raw = self._fetch_json("previews", dt)
        if not raw:
            return {}
        return self._parse_previews(raw)

    # ──────────────────────────────────────
    # 公開メソッド：場を絞った取得
    # ──────────────────────────────────────

    def get_venue_races(
        self,
        dt: date,
        stadium_number: int,
    ) -> list[RaceProgram]:
        """
        指定日・指定場の全レース出走表を取得する。

        Args:
            dt:             取得対象の日付
            stadium_number: 場番号（例: 24 = 大村）

        Returns:
            RaceProgram のリスト（レース番号昇順）
        """
        all_programs = self.fetch_programs(dt)
        races = [p for p in all_programs
                 if p.stadium_number == stadium_number]
        races.sort(key=lambda r: r.race_number)
        logger.info(
            "get_venue_races: stadium={}, date={}, {}レース取得".format(
                stadium_number, dt, len(races)
            )
        )
        return races

    def get_venue_results(
        self,
        dt: date,
        stadium_number: int,
    ) -> list[RaceResult]:
        """指定日・指定場の全レース結果を取得する。"""
        all_results = self.fetch_results(dt)
        results = [r for r in all_results
                   if r.stadium_number == stadium_number]
        results.sort(key=lambda r: r.race_number)
        logger.info(
            "get_venue_results: stadium={}, date={}, {}レース取得".format(
                stadium_number, dt, len(results)
            )
        )
        return results

    def get_venue_races_with_previews(
        self,
        dt: date,
        stadium_number: int,
    ) -> list[RaceProgram]:
        """
        出走表と直前情報を統合して取得する。
        直前情報が取得できた艇は course_number が実際のコースに更新される。

        Args:
            dt:             取得対象の日付
            stadium_number: 場番号

        Returns:
            直前情報を統合済みの RaceProgram リスト
        """
        races    = self.get_venue_races(dt, stadium_number)
        previews = self.fetch_previews(dt)

        for race in races:
            key = "{}_{}".format(stadium_number, race.race_number)
            exh_list = previews.get(key, [])
            if exh_list:
                race.exhibitions = exh_list
                # コース番号を直前情報で上書き
                exh_by_boat = {e.boat_number: e for e in exh_list}
                for entry in race.entries:
                    exh = exh_by_boat.get(entry.boat_number)
                    if exh and exh.course_number is not None:
                        entry.course_number = exh.course_number

        return races

    # ──────────────────────────────────────
    # 内部ヘルパー：HTTP 取得
    # ──────────────────────────────────────

    def _fetch_json(
        self,
        data_type: str,
        dt: date,
    ) -> Optional[dict]:
        """キャッシュ優先でJSONを取得する。"""
        cached = self._load_cache(dt, data_type)
        if cached is not None:
            logger.debug("キャッシュ使用: {}/{}".format(data_type, dt))
            return cached

        url = _url(data_type, dt)
        for attempt in range(1, self._RETRY_COUNT + 1):
            try:
                logger.info(
                    "API取得 ({}/{}): {}".format(
                        attempt, self._RETRY_COUNT, url
                    )
                )
                resp = self.session.get(url, timeout=20)

                if resp.status_code == 404:
                    logger.info("データなし(404): {}".format(url))
                    return None

                if resp.status_code != 200:
                    logger.warning(
                        "ステータス異常: {} {}".format(
                            resp.status_code, url
                        )
                    )
                    if attempt < self._RETRY_COUNT:
                        time.sleep(self._RETRY_WAIT * attempt)
                    continue

                data = resp.json()
                self._save_cache(dt, data_type, data)
                return data

            except requests.Timeout:
                logger.warning(
                    "タイムアウト ({}): {}".format(attempt, url)
                )
            except requests.ConnectionError as e:
                logger.warning(
                    "接続エラー ({}): {}".format(attempt, e)
                )
            except ValueError as e:
                logger.error("JSONパースエラー: {}".format(e))
                return None

            if attempt < self._RETRY_COUNT:
                time.sleep(self._RETRY_WAIT * attempt)

        logger.error("リトライ上限超過: {}".format(url))
        return None

    # ──────────────────────────────────────
    # 内部ヘルパー：パース
    # ──────────────────────────────────────

    def _parse_programs(self, raw: dict, dt: date) -> list[RaceProgram]:
        """programs JSON → RaceProgram リスト"""
        programs = []
        for race_raw in raw.get("programs", []):
            try:
                program = self._parse_single_program(race_raw)
                if program:
                    programs.append(program)
            except Exception as e:
                logger.warning(
                    "programパースエラー "
                    "(stadium={}, no={}): {}".format(
                        race_raw.get("stadium_number"),
                        race_raw.get("number"),
                        e,
                    )
                )
        logger.info(
            "出走表パース完了: {}レース ({})".format(len(programs), dt)
        )
        return programs

    def _parse_single_program(self, d: dict) -> Optional[RaceProgram]:
        """1レース分の出走表 dict → RaceProgram"""
        stadium_no = int(d.get("stadium_number", 0))
        venue_name, venue_id = STADIUM_MAP.get(
            stadium_no,
            (f"場{stadium_no}", str(stadium_no).zfill(2))
        )

        entries = []
        for boat_raw in d.get("boats", []):
            entry = RaceEntry.from_dict(boat_raw)
            if entry.boat_number > 0:
                entries.append(entry)
        entries.sort(key=lambda e: e.boat_number)

        if not entries:
            return None

        return RaceProgram(
            stadium_number = stadium_no,
            venue_id       = venue_id,
            venue_name     = venue_name,
            race_number    = int(d.get("number", 0)),
            race_date      = str(d.get("date", "")),
            grade_label    = str(d.get("grade_label", "一般")),
            title          = str(d.get("title", "")),
            distance       = int(d.get("distance", 1800)),
            entries        = entries,
            weather        = WeatherInfo.from_dict(d),
        )

    def _parse_results(self, raw: dict, dt: date) -> list[RaceResult]:
        """results JSON → RaceResult リスト（未確定レースは除外）"""
        results = []
        for race_raw in raw.get("results", []):
            try:
                result = RaceResult.from_dict(race_raw)
                if result is not None:          # ← 未確定レースを除外
                    results.append(result)
            except Exception as e:
                logger.warning("resultパースエラー: {}".format(e))
        logger.info(
            "結果パース完了: {}レース ({})".format(len(results), dt)
        )
        return results


    def _parse_previews(
        self, raw: dict
    ) -> dict[str, list[ExhibitionInfo]]:
        """
        previews JSON → ExhibitionInfo 辞書

        previews の boats は艇番をキーとする辞書形式:
        {"1": {...}, "2": {...}, ...}
        """
        previews: dict[str, list[ExhibitionInfo]] = {}
        for race_raw in raw.get("previews", []):
            try:
                stadium_no = int(race_raw.get("stadium_number", 0))
                race_no    = int(race_raw.get("number", 0))
                key        = "{}_{}".format(stadium_no, race_no)

                boats_dict = race_raw.get("boats", {})
                exh_list   = []

                # boats は {"1": {...}, "2": {...}} 形式
                for boat_key, boat_data in boats_dict.items():
                    exh = ExhibitionInfo.from_dict(
                        int(boat_key), boat_data
                    )
                    exh_list.append(exh)

                exh_list.sort(key=lambda e: e.boat_number)
                previews[key] = exh_list

            except Exception as e:
                logger.warning("previewパースエラー: {}".format(e))

        return previews

    # ──────────────────────────────────────
    # 内部ヘルパー：キャッシュ
    # ──────────────────────────────────────

    def _cache_path(self, dt: date, data_type: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "{}_{}.json".format(
            dt.strftime("%Y%m%d"), data_type
        )

    def _load_cache(self, dt: date, data_type: str) -> Optional[dict]:
        path = self._cache_path(dt, data_type)
        if path and path.exists():
            try:
                with path.open(encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("キャッシュ読み込みエラー: {}".format(e))
        return None

    def _save_cache(self, dt: date, data_type: str, data: dict) -> None:
        path = self._cache_path(dt, data_type)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("キャッシュ保存: {}".format(path))
        except Exception as e:
            logger.warning("キャッシュ保存エラー: {}".format(e))
