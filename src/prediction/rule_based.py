# src/prediction/rule_based.py
"""
ルールベース予測モデル

各艇に複数の観点からスコアを付け、
本命・対抗・穴・買い目を決定する。

スコアリング設計:
  各観点を0〜1に正規化してから重みを掛け合わせ、
  最終スコアは0〜100のポイントとして返す。
  重みの合計が100になるよう設定する。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import logging

from src.prediction.feature_builder import RaceFeatures, BoatFeatures

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# スコアリング重みテーブル
# ──────────────────────────────────────────

# 直前情報なし版（programs のみ）
_WEIGHTS_NO_EXHIBITION = {
    "course_advantage":   30,   # コース有利度（最重要）
    "motor_in2_rate":     20,   # モーター2連率
    "national_win_rate":  15,   # 全国勝率
    "local_win_rate":     15,   # 当地勝率
    "grade_score":        10,   # 級別
    "avg_start_timing":   10,   # 平均ST
}

# 直前情報あり版（previews 統合後）
_WEIGHTS_WITH_EXHIBITION = {
    "course_advantage":   25,
    "motor_in2_rate":     15,
    "national_win_rate":  12,
    "local_win_rate":     12,
    "grade_score":         8,
    "avg_start_timing":    8,
    "exhibition_time":    10,   # 展示タイム
    "exhibition_st":      10,   # 展示ST
}

# 荒れ水面補正（風速大・波高大の場合）
# コース有利度の重みを下げ、選手実力を上げる
_WEIGHTS_ROUGH = {
    "course_advantage":   15,
    "motor_in2_rate":     20,
    "national_win_rate":  20,
    "local_win_rate":     20,
    "grade_score":        15,
    "avg_start_timing":   10,
}


# ──────────────────────────────────────────
# 予測結果データクラス
# ──────────────────────────────────────────

@dataclass
class BoatScore:
    """1艇分のスコアリング結果。"""
    boat_number: int
    course_number: int
    racer_name: str
    grade: str
    total_score: float            # 総合スコア（高いほど有力）
    score_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def score_display(self) -> str:
        return f"{self.total_score:.1f}pt"


@dataclass
class BuyTarget:
    """買い目1点分。"""
    combination: str              # 例: "1-2-3"
    bet_type: str                 # "trifecta"（3連単）/ "exacta"（2連単）
    reason: str                   # 買い理由
    priority: int                 # 1=本線 2=対抗 3=押さえ


@dataclass
class Prediction:
    """
    1レース分の予測結果。
    記事生成モジュールへの入力となる。
    """
    race_id: str
    venue_id: str
    venue_name: str
    race_number: int
    race_date: str
    grade_label: str
    title: str

    # 天候
    weather: str
    wind_effect: str

    # スコアランキング（高得点順）
    ranked_boats: list[BoatScore]

    # 予想
    honmei: BoatScore             # 本命（1位）
    taikou: BoatScore             # 対抗（2位）
    ana: Optional[BoatScore]      # 穴（3位、条件付き）

    # 買い目
    buy_targets: list[BuyTarget]

    # 予測信頼度コメント
    confidence: str               # "高" / "中" / "低"
    confidence_reason: str        # 信頼度の根拠

    # フラグ
    is_rough_condition: bool      # 荒れ条件かどうか
    has_exhibition: bool          # 直前情報使用かどうか

    @property
    def honmei_name(self) -> str:
        return (
            f"{self.honmei.course_number}号艇 "
            f"{self.honmei.racer_name}（{self.honmei.grade}）"
        )

    @property
    def taikou_name(self) -> str:
        return (
            f"{self.taikou.course_number}号艇 "
            f"{self.taikou.racer_name}（{self.taikou.grade}）"
        )

    @property
    def trifecta_targets(self) -> list[BuyTarget]:
        return [b for b in self.buy_targets if b.bet_type == "trifecta"]

    @property
    def exacta_targets(self) -> list[BuyTarget]:
        return [b for b in self.buy_targets if b.bet_type == "exacta"]


# ──────────────────────────────────────────
# RuleBasedPredictor
# ──────────────────────────────────────────

class RuleBasedPredictor:
    """
    ルールベースの予測モデル。

    使い方:
        predictor = RuleBasedPredictor()
        prediction = predictor.predict(race_features)
    """

    # 穴判定閾値：3位スコアが1位の何%以上なら穴として紹介するか
    _ANA_THRESHOLD = 0.72

    # 信頼度判定：1位と2位のスコア差
    _CONFIDENCE_HIGH_GAP = 15.0
    _CONFIDENCE_LOW_GAP  = 5.0

    def predict(self, features: RaceFeatures) -> Prediction:
        """
        RaceFeatures から Prediction を生成する。
        """
        weights = self._select_weights(features)

        scored: list[BoatScore] = []
        for boat in features.boats:
            score = self._score_boat(boat, weights, features)
            scored.append(score)

        ranked = sorted(scored, key=lambda s: s.total_score, reverse=True)

        honmei = ranked[0]
        taikou = ranked[1] if len(ranked) > 1 else ranked[0]
        ana    = self._select_ana(ranked)

        # ranked を渡す（BoatScore のリスト）
        buy_targets = self._build_buy_targets(
            honmei, taikou, ana, ranked, features
        )

        confidence, confidence_reason = self._judge_confidence(
            ranked, features
        )

        return Prediction(
            race_id            = features.race_id,
            venue_id           = features.venue_id,
            venue_name         = features.venue_name,
            race_number        = features.race_number,
            race_date          = features.race_date,
            grade_label        = features.grade_label,
            title              = features.title,
            weather            = features.weather,
            wind_effect        = self._wind_effect_text(features),
            ranked_boats       = ranked,
            honmei             = honmei,
            taikou             = taikou,
            ana                = ana,
            buy_targets        = buy_targets,
            confidence         = confidence,
            confidence_reason  = confidence_reason,
            is_rough_condition = features.is_rough_condition,
            has_exhibition     = any(
                b.exhibition_time is not None for b in features.boats
            ),
        )


    # ──────────────────────────────────────
    # スコアリング
    # ──────────────────────────────────────

    def _select_weights(self, features: RaceFeatures) -> dict[str, int]:
        """水面状況に応じて重みテーブルを選択する。"""
        if features.is_rough_condition:
            logger.debug("荒れ水面補正を適用")
            return _WEIGHTS_ROUGH
        if any(b.has_exhibition for b in features.boats):
            return _WEIGHTS_WITH_EXHIBITION
        return _WEIGHTS_NO_EXHIBITION

    def _score_boat(
        self,
        boat: BoatFeatures,
        weights: dict[str, int],
        features: RaceFeatures,
    ) -> BoatScore:
        """1艇のスコアを計算する。"""
        breakdown: dict[str, float] = {}
        total = 0.0

        # ── コース有利度 ────────────────────────
        if "course_advantage" in weights:
            s = boat.course_advantage * weights["course_advantage"]
            breakdown["course_advantage"] = round(s, 2)
            total += s

        # ── モーター2連率 ───────────────────────
        if "motor_in2_rate" in weights:
            # 50%基準で正規化（最大1.0）
            norm = min(boat.motor_in2_rate / 100.0, 1.0)
            s = norm * weights["motor_in2_rate"]
            breakdown["motor_in2_rate"] = round(s, 2)
            total += s

        # ── 全国勝率 ────────────────────────────
        if "national_win_rate" in weights:
            # 8.0勝率を満点基準
            norm = min(boat.national_win_rate / 8.0, 1.0)
            s = norm * weights["national_win_rate"]
            breakdown["national_win_rate"] = round(s, 2)
            total += s

        # ── 当地勝率 ────────────────────────────
        if "local_win_rate" in weights:
            norm = min(boat.local_win_rate / 8.0, 1.0)
            s = norm * weights["local_win_rate"]
            breakdown["local_win_rate"] = round(s, 2)
            total += s

        # ── 級別スコア ──────────────────────────
        if "grade_score" in weights:
            # A1=4 を満点基準
            norm = boat.grade_score / 4.0
            s = norm * weights["grade_score"]
            breakdown["grade_score"] = round(s, 2)
            total += s

        # ── 平均ST ──────────────────────────────
        if "avg_start_timing" in weights:
            # ST 0.10秒を満点、0.20秒以上を0点
            raw_st = boat.avg_start_timing
            if raw_st <= 0.0:
                norm = 0.5   # データなしは中間値
            else:
                norm = max(0.0, (0.20 - raw_st) / 0.10)
                norm = min(norm, 1.0)
            # Fリスクがある場合はST加点を50%カット
            if boat.f_risk:
                norm *= 0.5
            s = norm * weights["avg_start_timing"]
            breakdown["avg_start_timing"] = round(s, 2)
            total += s

        # ── 展示タイム ──────────────────────────
        if "exhibition_time" in weights and boat.exhibition_time:
            # 展示タイムは小さいほど良い（6.5秒基準・0.5秒幅）
            norm = max(0.0, (boat.exhibition_time - 6.5) / 0.5)
            norm = min(1.0 - norm, 1.0)
            s = norm * weights["exhibition_time"]
            breakdown["exhibition_time"] = round(s, 2)
            total += s

        # ── 展示ST ──────────────────────────────
        if "exhibition_st" in weights and boat.exhibition_st is not None:
            raw = boat.exhibition_st
            norm = max(0.0, (0.20 - raw) / 0.10)
            norm = min(norm, 1.0)
            s = norm * weights["exhibition_st"]
            breakdown["exhibition_st"] = round(s, 2)
            total += s

        return BoatScore(
            boat_number     = boat.boat_number,
            course_number   = boat.course_number,
            racer_name      = boat.racer_name,
            grade           = boat.grade,
            total_score     = round(total, 2),
            score_breakdown = breakdown,
        )

    # ──────────────────────────────────────
    # 穴選出
    # ──────────────────────────────────────

    def _select_ana(
        self, ranked: list[BoatScore]
    ) -> Optional[BoatScore]:
        """
        3位艇を穴として選出するかどうかを判定する。

        本命スコアの _ANA_THRESHOLD 以上のスコアを持つ場合のみ穴として紹介。
        スコア差が小さすぎる場合（実力拮抗）は穴ではなく「混戦」扱い。
        """
        if len(ranked) < 3:
            return None
        third = ranked[2]
        top   = ranked[0]
        ratio = third.total_score / top.total_score if top.total_score > 0 else 0
        if ratio >= self._ANA_THRESHOLD:
            return third
        return None

    # ──────────────────────────────────────
    # 買い目生成
    # ──────────────────────────────────────

    def _build_buy_targets(
        self,
        honmei: BoatScore,
        taikou: BoatScore,
        ana: Optional[BoatScore],
        ranked: list[BoatScore],     # ← BoatScore のリストに変更
        features: RaceFeatures,
    ) -> list[BuyTarget]:
        """
        3連単・2連単の買い目リストを生成する。
        """
        targets: list[BuyTarget] = []
        hc = honmei.course_number
        tc = taikou.course_number
        ac = ana.course_number if ana else None

        # 本命・対抗・穴以外の艇をスコア順で取得（BoatScore から）
        others = [
            b.course_number for b in ranked
            if b.course_number not in (hc, tc)
               and (ac is None or b.course_number != ac)
        ]

        # ── 3連単 ───────────────────────────────
        # 本線：本命-対抗-3位スコア艇
        third_c = others[0] if others else (
            ac if ac else (
                next(
                    (b.course_number for b in ranked
                     if b.course_number not in (hc, tc)),
                    hc
                )
            )
        )

        targets.append(BuyTarget(
            combination = f"{hc}-{tc}-{third_c}",
            bet_type    = "trifecta",
            reason      = "本線：本命1着・対抗2着",
            priority    = 1,
        ))

        targets.append(BuyTarget(
            combination = f"{hc}-{third_c}-{tc}",
            bet_type    = "trifecta",
            reason      = "本線：本命1着・対抗3着",
            priority    = 1,
        ))

        # 穴：本命軸で穴を絡める
        if ac and ac not in (tc, third_c):
            targets.append(BuyTarget(
                combination = f"{hc}-{ac}-{tc}",
                bet_type    = "trifecta",
                reason      = f"穴：{ac}号艇が2着に来た場合",
                priority    = 2,
            ))
            targets.append(BuyTarget(
                combination = f"{hc}-{tc}-{ac}",
                bet_type    = "trifecta",
                reason      = f"穴：{ac}号艇が3着に入る場合",
                priority    = 2,
            ))

        # 荒れ条件：対抗軸も追加
        if features.is_rough_condition:
            targets.append(BuyTarget(
                combination = f"{tc}-{hc}-{third_c}",
                bet_type    = "trifecta",
                reason      = "荒れ想定：対抗1着に切り替え",
                priority    = 3,
            ))

        # ── 2連単（保険） ───────────────────────
        targets.append(BuyTarget(
            combination = f"{hc}-{tc}",
            bet_type    = "exacta",
            reason      = "本命-対抗 本線保険",
            priority    = 1,
        ))
        if ac:
            targets.append(BuyTarget(
                combination = f"{hc}-{ac}",
                bet_type    = "exacta",
                reason      = "本命-穴 保険",
                priority    = 2,
            ))

        return targets


    # ──────────────────────────────────────
    # 信頼度判定
    # ──────────────────────────────────────

    def _judge_confidence(
        self,
        ranked: list[BoatScore],
        features: RaceFeatures,
    ) -> tuple[str, str]:
        """
        予測の信頼度を判定する。

        Returns:
            (confidence: "高"/"中"/"低", reason: str)
        """
        if len(ranked) < 2:
            return "低", "出走艇データが不足しています"

        gap = ranked[0].total_score - ranked[1].total_score

        # 荒れ条件は信頼度を下げる
        if features.is_rough_condition:
            return "低", "強風・高波のため荒れやすい条件です"

        # 本命がインコースかどうか
        pole_is_honmei = ranked[0].course_number == 1

        if gap >= self._CONFIDENCE_HIGH_GAP and pole_is_honmei:
            reason = (
                f"1コースの{ranked[0].racer_name}選手がデータで頭一つ抜けており、"
                f"イン逃げ本命の鉄板レースと判断"
            )
            return "高", reason

        if gap >= self._CONFIDENCE_HIGH_GAP:
            reason = (
                f"{ranked[0].course_number}コースの{ranked[0].racer_name}選手が"
                f"スコアで大きくリード（差={gap:.1f}pt）"
            )
            return "高", reason

        if gap <= self._CONFIDENCE_LOW_GAP:
            reason = (
                f"上位艇のスコア差が僅差（差={gap:.1f}pt）で混戦模様。"
                f"波乱の可能性あり"
            )
            return "低", reason

        reason = (
            f"{ranked[0].racer_name}選手がやや優勢（差={gap:.1f}pt）。"
            f"標準的なレース展開を予想"
        )
        return "中", reason

    def _wind_effect_text(self, features: RaceFeatures) -> str:
        """風向き・風速を日本語テキストで返す。"""
        if features.wind_speed == 0:
            return "無風"
        level_map = {0: "影響なし", 1: "影響小", 2: "影響中", 3: "影響大・荒れ注意"}
        level_text = level_map.get(features.wind_effect_level, "")
        return (
            f"{features.wind_direction}風 {features.wind_speed}m/s"
            f"（{level_text}）"
        )
