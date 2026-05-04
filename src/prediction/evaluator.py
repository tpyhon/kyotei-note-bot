# src/prediction/evaluator.py
"""
予測精度の自己評価・的中履歴の蓄積

毎日の予測結果と実際の結果を照合し、
data/results/ に JSON で蓄積する。
X告知文や記事冒頭の「前日結果報告」に使用する。
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Optional

from src.prediction.rule_based import Prediction
from src.data.models import RaceResult

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("data/results")


# ──────────────────────────────────────────
# 評価結果データクラス
# ──────────────────────────────────────────

@dataclass
class EvaluationRecord:
    """
    1レース分の予測 vs 実績の記録。
    data/results/{YYYYMMDD}.json に保存される。
    """
    race_id: str
    race_date: str
    venue_name: str
    race_number: int

    # 予測
    predicted_honmei_course: int
    predicted_taikou_course: int
    predicted_trifecta: list[str]      # 予測した3連単買い目リスト
    predicted_exacta: list[str]        # 予測した2連単買い目リスト

    # 実績
    actual_finishing_order: list[int]  # 実際の着順コースリスト
    actual_trifecta: str               # 実際の3連単 例: "1-2-3"
    actual_trifecta_amount: int        # 実際の3連単払戻
    actual_exacta: str
    actual_exacta_amount: int

    # 的中判定
    honmei_hit: bool                   # 本命1着的中
    trifecta_hit: bool                 # 3連単的中
    exacta_hit: bool                   # 2連単的中

    # Note記事URL（投稿後に設定）
    note_url: str = ""


# ──────────────────────────────────────────
# Evaluator
# ──────────────────────────────────────────

class Evaluator:
    """
    予測と実績を照合して的中履歴を管理するクラス。

    使い方:
        evaluator = Evaluator()

        # 予測と実績を照合して保存
        record = evaluator.evaluate(prediction, actual_result)

        # 昨日の結果サマリーを取得（記事冒頭用）
        summary = evaluator.get_yesterday_summary(venue_id="24")
    """

    def __init__(self, results_dir: Path = RESULTS_DIR):
        self.results_dir = results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def evaluate(
        self,
        prediction: Prediction,
        actual: RaceResult,
    ) -> EvaluationRecord:
        """
        予測と実績を照合して EvaluationRecord を生成・保存する。

        Args:
            prediction: 予測結果
            actual:     実際のレース結果

        Returns:
            EvaluationRecord
        """
        predicted_trifecta = [
            t.combination for t in prediction.trifecta_targets
        ]
        predicted_exacta = [
            e.combination for e in prediction.exacta_targets
        ]

        # 本命1着的中
        honmei_hit = (
            actual.winner_boat == prediction.honmei.boat_number
        )

        # 3連単的中（予測買い目の中に実際の組み合わせが含まれるか）
        trifecta_hit = actual.trifecta_combination in predicted_trifecta

        # 2連単的中
        exacta_hit = actual.exacta_combination in predicted_exacta

        record = EvaluationRecord(
            race_id                  = prediction.race_id,
            race_date                = prediction.race_date,
            venue_name               = prediction.venue_name,
            race_number              = prediction.race_number,
            predicted_honmei_course  = prediction.honmei.course_number,
            predicted_taikou_course  = prediction.taikou.course_number,
            predicted_trifecta       = predicted_trifecta,
            predicted_exacta         = predicted_exacta,
            actual_finishing_order   = actual.finishing_order,
            actual_trifecta          = actual.trifecta_combination,
            actual_trifecta_amount   = actual.trifecta_amount,
            actual_exacta            = actual.exacta_combination,
            actual_exacta_amount     = actual.exacta_amount,
            honmei_hit               = honmei_hit,
            trifecta_hit             = trifecta_hit,
            exacta_hit               = exacta_hit,
        )

        self._save(record)
        self._log_result(record)
        return record

    def get_yesterday_summary(
        self,
        venue_id: str,
        target_date: Optional[date] = None,
    ) -> Optional[str]:
        """
        指定日（デフォルト昨日）の的中結果サマリーを返す。
        Note記事の冒頭「前日結果報告」に使用する。

        Returns:
            サマリー文字列。記録がない場合は None。
        """
        from datetime import date as _date, timedelta
        if target_date is None:
            target_date = _date.today() - timedelta(days=1)

        records = self._load(target_date)
        venue_records = [
            r for r in records
            if venue_id in r.race_id
        ]

        if not venue_records:
            return None

        total       = len(venue_records)
        honmei_hits = sum(1 for r in venue_records if r.honmei_hit)
        tri_hits    = sum(1 for r in venue_records if r.trifecta_hit)
        ex_hits     = sum(1 for r in venue_records if r.exacta_hit)

        # 最大払戻を取得
        best_tri = max(
            venue_records,
            key=lambda r: r.actual_trifecta_amount,
        )

        lines = [
            f"📊 **前日({target_date.strftime('%m/%d')})の結果報告**",
            f"本命的中: {honmei_hits}/{total}レース",
            f"3連単的中: {tri_hits}/{total}レース",
            f"2連単的中: {ex_hits}/{total}レース",
        ]
        if best_tri.trifecta_hit and best_tri.actual_trifecta_amount > 0:
            lines.append(
                f"最高払戻: {best_tri.actual_trifecta_amount:,}円"
                f"（{best_tri.actual_trifecta}）✨"
            )

        return "\n".join(lines)

    def get_running_stats(
        self,
        venue_id: str,
        days: int = 7,
    ) -> dict:
        """
        直近N日間の的中率統計を返す（記事の信頼感演出用）。

        Returns:
            {
                "total": int,
                "honmei_rate": float,
                "trifecta_rate": float,
                "exacta_rate": float,
                "best_payout": int,
            }
        """
        from datetime import date as _date, timedelta
        all_records = []
        today = _date.today()
        for i in range(1, days + 1):
            dt = today - timedelta(days=i)
            records = self._load(dt)
            all_records.extend(
                r for r in records if venue_id in r.race_id
            )

        if not all_records:
            return {
                "total": 0,
                "honmei_rate": 0.0,
                "trifecta_rate": 0.0,
                "exacta_rate": 0.0,
                "best_payout": 0,
            }

        total = len(all_records)
        return {
            "total":          total,
            "honmei_rate":    round(
                sum(1 for r in all_records if r.honmei_hit) / total, 3
            ),
            "trifecta_rate":  round(
                sum(1 for r in all_records if r.trifecta_hit) / total, 3
            ),
            "exacta_rate":    round(
                sum(1 for r in all_records if r.exacta_hit) / total, 3
            ),
            "best_payout":    max(
                r.actual_trifecta_amount for r in all_records
            ),
        }

    # ──────────────────────────────────────
    # 内部ヘルパー：保存・読み込み
    # ──────────────────────────────────────

    def _file_path(self, dt: date) -> Path:
        return self.results_dir / f"{dt.strftime('%Y%m%d')}_eval.json"

    def _save(self, record: EvaluationRecord) -> None:
        """当日の評価ファイルに追記保存する。"""
        from datetime import date as _date
        dt = _date.fromisoformat(record.race_date)
        path = self._file_path(dt)

        existing = self._load(dt)

        # 同じrace_idがあれば上書き、なければ追加
        updated = [r for r in existing if r.race_id != record.race_id]
        updated.append(record)

        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(
                    [asdict(r) for r in updated],
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"評価記録保存: {record.race_id}")
        except Exception as e:
            logger.error(f"評価記録保存エラー: {e}")

    def _load(self, dt: date) -> list[EvaluationRecord]:
        """指定日の評価ファイルを読み込む。"""
        path = self._file_path(dt)
        if not path.exists():
            return []
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            return [EvaluationRecord(**d) for d in data]
        except Exception as e:
            logger.warning(f"評価記録読み込みエラー: {e}")
            return []

    def _log_result(self, record: EvaluationRecord) -> None:
        """的中結果をログ出力する。"""
        hits = []
        if record.honmei_hit:
            hits.append("本命的中✅")
        if record.trifecta_hit:
            hits.append(f"3連単的中✅({record.actual_trifecta_amount:,}円)")
        if record.exacta_hit:
            hits.append(f"2連単的中✅({record.actual_exacta_amount:,}円)")
        if not hits:
            hits.append("不的中❌")

        logger.info(
            f"評価完了 [{record.race_id}] "
            f"実際:{record.actual_trifecta} "
            f"→ {' / '.join(hits)}"
        )
