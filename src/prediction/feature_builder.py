# src/prediction/feature_builder.py
"""
特徴量エンジニアリング

RaceProgram から予測モデルが使う数値特徴量を生成する。
各艇を1つの BoatFeatures dataclass に変換し、
RaceFeatures として1レース分をまとめる。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from src.data.models import RaceProgram, RaceEntry, VenueConfig


# ──────────────────────────────────────────
# 特徴量データクラス
# ──────────────────────────────────────────

@dataclass
class BoatFeatures:
    """
    1艇分の特徴量。
    全て数値に正規化済みで予測スコア計算に直接使える。
    """
    boat_number: int
    course_number: int
    racer_name: str
    grade: str

    # ── 選手成績 ──────────────────────────
    national_win_rate: float      # 全国勝率
    local_win_rate: float         # 当地勝率
    national_in2_rate: float      # 全国2連率
    local_in2_rate: float         # 当地2連率
    avg_start_timing: float       # 平均ST（小さいほど良い）
    flying_count: int             # F回数（多いほどリスク）
    late_count: int               # L回数
    grade_score: int              # 級別スコア A1=4〜B2=1

    # ── モーター・ボート ───────────────────
    motor_in2_rate: float         # モーター2連率
    motor_in3_rate: float         # モーター3連率
    boat_in2_rate: float          # ボート2連率

    # ── コース有利度 ───────────────────────
    course_advantage: float       # コース有利スコア（後述）
    venue_in_win_rate: float      # 当場インコース1着率

    # ── 展示情報（直前情報取得後に設定） ────
    exhibition_time: Optional[float] = None
    exhibition_st: Optional[float]   = None

    @property
    def has_exhibition(self) -> bool:
        return self.exhibition_time is not None

    @property
    def f_risk(self) -> bool:
        """F持ちでスタートが早い選手はフライングリスクあり。"""
        return (
            self.flying_count >= 1
            and self.avg_start_timing <= 0.10
        )


@dataclass
class RaceFeatures:
    """
    1レース分の特徴量セット。
    予測モデルへの入力となる。
    """
    race_id: str
    venue_id: str
    venue_name: str
    race_number: int
    race_date: str
    grade_label: str
    title: str

    # 天候特徴量
    weather: str
    wind_direction: str
    wind_speed: int
    wave_height: int
    air_temperature: float
    water_temperature: float
    wind_effect_level: int        # 0=無風 1=影響小 2=影響中 3=影響大

    # 6艇分の特徴量（boat_number順）
    boats: list[BoatFeatures] = field(default_factory=list)

    @property
    def boat_by_course(self) -> dict[int, BoatFeatures]:
        return {b.course_number: b for b in self.boats}

    @property
    def boat_by_number(self) -> dict[int, BoatFeatures]:
        return {b.boat_number: b for b in self.boats}

    @property
    def pole_boat(self) -> Optional[BoatFeatures]:
        """1コースの艇。"""
        return self.boat_by_course.get(1)

    @property
    def is_rough_condition(self) -> bool:
        """荒れやすい条件かどうか。"""
        return self.wind_effect_level >= 3 or self.wave_height >= 10


# ──────────────────────────────────────────
# コース有利度テーブル
# ──────────────────────────────────────────

# 全国平均のコース別1着率（一般戦ベース）
# 出典: 業界統計データ
_COURSE_BASE_WIN_RATE: dict[int, float] = {
    1: 0.550,   # イン
    2: 0.148,
    3: 0.113,
    4: 0.087,
    5: 0.060,
    6: 0.042,
}


def _course_advantage(course: int, venue_in_win_rate: float) -> float:
    """
    コース番号と当場インコース勝率から有利度スコアを計算する。

    当場のインコース勝率を全国平均（55%）との比率でスケーリングし、
    各コースの基本有利度に掛け合わせる。

    Returns:
        0.0〜1.0 の有利度スコア
    """
    base = _COURSE_BASE_WIN_RATE.get(course, 0.04)
    # インコース勝率のスケーリング係数（全国平均55%基準）
    in_scale = venue_in_win_rate / 0.55
    # コース1はスケーリングそのまま、外コースはインが強い場ほど不利
    if course == 1:
        return min(base * in_scale, 1.0)
    else:
        # アウトコースはインが強い場ほど有利度が下がる
        outer_scale = 2.0 - in_scale   # in_scale>1 → outer_scale<1
        return max(base * outer_scale, 0.01)


def _wind_effect_level(wind_speed: int) -> int:
    """風速から影響レベルを返す。0=無風 1=影響小 2=影響中 3=影響大"""
    if wind_speed == 0:
        return 0
    if wind_speed <= 2:
        return 1
    if wind_speed <= 4:
        return 2
    return 3


# ──────────────────────────────────────────
# FeatureBuilder
# ──────────────────────────────────────────

class FeatureBuilder:
    """
    RaceProgram → RaceFeatures に変換するクラス。

    使い方:
        builder = FeatureBuilder(venue_config)
        features = builder.build(race_program)
    """

    def __init__(self, venue_config: Optional[VenueConfig] = None):
        """
        Args:
            venue_config: 競艇場設定（インコース勝率などに使用）。
                          None の場合は全国平均値を使用。
        """
        self.venue_config = venue_config
        self._in_win_rate = (
            venue_config.in_course_win_rate
            if venue_config else 0.55
        )

    def build(self, program: RaceProgram) -> RaceFeatures:
        """
        RaceProgram から RaceFeatures を生成する。

        Args:
            program: 出走表データ（直前情報統合済みが望ましい）

        Returns:
            RaceFeatures
        """
        # 天候特徴量
        w = program.weather
        wind_level = _wind_effect_level(w.wind_speed)

        # 直前情報を辞書化
        exh_by_boat: dict[int, tuple[float, Optional[float]]] = {}
        for exh in program.exhibitions:
            exh_by_boat[exh.boat_number] = (
                exh.exhibition_time,
                exh.start_timing,
            )

        # 6艇分の特徴量を生成
        boat_features = []
        for entry in program.entries:
            bf = self._build_boat_features(
                entry, exh_by_boat
            )
            boat_features.append(bf)

        return RaceFeatures(
            race_id          = program.race_id,
            venue_id         = program.venue_id,
            venue_name       = program.venue_name,
            race_number      = program.race_number,
            race_date        = program.race_date,
            grade_label      = program.grade_label,
            title            = program.title,
            weather          = w.weather,
            wind_direction   = w.wind_direction,
            wind_speed       = w.wind_speed,
            wave_height      = w.wave_height,
            air_temperature  = w.air_temperature,
            water_temperature= w.water_temperature,
            wind_effect_level= wind_level,
            boats            = boat_features,
        )

    def _build_boat_features(
        self,
        entry: RaceEntry,
        exh_by_boat: dict[int, tuple[float, Optional[float]]],
    ) -> BoatFeatures:
        """1艇分の BoatFeatures を生成する。"""
        racer = entry.racer
        motor = entry.motor_boat
        exh   = exh_by_boat.get(entry.boat_number)

        return BoatFeatures(
            boat_number       = entry.boat_number,
            course_number     = entry.course_number,
            racer_name        = racer.name,
            grade             = racer.grade,
            national_win_rate = racer.national_win_rate,
            local_win_rate    = racer.local_win_rate,
            national_in2_rate = racer.national_in2_rate,
            local_in2_rate    = racer.local_in2_rate,
            avg_start_timing  = racer.avg_start_timing,
            flying_count      = racer.flying_count,
            late_count        = racer.late_count,
            grade_score       = racer.grade_score,
            motor_in2_rate    = motor.motor_in2_rate,
            motor_in3_rate    = motor.motor_in3_rate,
            boat_in2_rate     = motor.boat_in2_rate,
            course_advantage  = _course_advantage(
                                    entry.course_number,
                                    self._in_win_rate
                                ),
            venue_in_win_rate = self._in_win_rate,
            exhibition_time   = exh[0] if exh else None,
            exhibition_st     = exh[1] if exh else None,
        )
