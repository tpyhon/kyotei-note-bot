"""
メインパイプライン
データ取得 → 予測 → 1会場1記事生成 → Note下書き保存 → X投稿文出力
"""
from __future__ import annotations

import logging
import os
import time
import sys
from datetime import date, timedelta
from pathlib import Path

# ── .env 読み込み ─────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import yaml

from src.data.boatrace_api import BoatraceAPIClient
from src.data.models import VenueConfig
from src.prediction.feature_builder import FeatureBuilder
from src.prediction.rule_based import RuleBasedPredictor
from src.prediction.evaluator import Evaluator
from src.generation.article_generator import ArticleGenerator
from src.generation.x_post_generator import XPostGenerator
from src.clients.note_client import NoteClient, markdown_to_note_html

logger = logging.getLogger(__name__)

ROOT        = Path(__file__).resolve().parent.parent
_VENUES_CFG = ROOT / "config" / "venues.yml"
_DATA_RAW   = ROOT / "data" / "raw"


# ------------------------------------------------------------------ #
#  設定読み込み                                                        #
# ------------------------------------------------------------------ #

def _load_venues() -> list[VenueConfig]:
    cfg = yaml.safe_load(_VENUES_CFG.read_text(encoding="utf-8"))
    return [VenueConfig.from_dict(v) for v in cfg.get("venues", [])]


# ------------------------------------------------------------------ #
#  Slack 通知（オプション）                                            #
# ------------------------------------------------------------------ #

def _notify_slack(message: str) -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook:
        return
    try:
        import requests
        requests.post(webhook, json={"text": message}, timeout=10)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Slack通知失敗: %s", exc)


# ------------------------------------------------------------------ #
#  レース選択                                                          #
# ------------------------------------------------------------------ #

def _select_races(races: list, max_count: int = 3) -> list:
    """
    対象レースを選択する。
    優先順位:
      1. 信頼度「高」のレース（最大3本、レース番号順）
      2. 信頼度高が0本の場合は 1R・6R・12R で補完
    """
    builder   = FeatureBuilder()
    predictor = RuleBasedPredictor()

    high_confidence = []
    for race in races:
        try:
            features = builder.build(race)
            pred     = predictor.predict(features)
            if pred.confidence == "高":
                high_confidence.append(race)
        except Exception:  # noqa: BLE001
            continue

    if high_confidence:
        selected = sorted(high_confidence, key=lambda r: r.race_number)[:max_count]
        logger.info(
            "信頼度「高」レース: %s",
            [f"{r.race_number}R" for r in selected],
        )
        return selected

    # 信頼度高がない場合は 1R・6R・12R を選択
    logger.info("信頼度「高」なし → 1R・6R・12R を使用")
    target_numbers = [1, 6, 12]
    selected = []
    for n in target_numbers:
        race = min(races, key=lambda r: abs(r.race_number - n))
        if race not in selected:
            selected.append(race)
    return selected


# ------------------------------------------------------------------ #
#  1会場まとめ処理                                                     #
# ------------------------------------------------------------------ #

def _process_venue(
    venue_config: VenueConfig,
    race_predictions: list[tuple],
    note_client: NoteClient,
    article_gen: ArticleGenerator,
    x_gen: XPostGenerator,
    evaluator: Evaluator,
    dry_run: bool,
) -> dict:
    """
    1会場・複数レース予測を1記事にまとめてNote下書き保存する。

    Args:
        venue_config    : 会場設定
        race_predictions: [(RaceProgram, Prediction), ...] のリスト
        note_client     : Note APIクライアント
        article_gen     : 記事生成クライアント
        x_gen           : X投稿文生成クライアント
        evaluator       : 評価記録クライアント
        dry_run         : Trueの場合Note投稿をスキップ
    Returns:
        {"venue": str, "race_numbers": list, "note_url": str, "x_post": str}
    """
    venue_name = venue_config.name
    result = {
        "venue":        venue_name,
        "race_numbers": [r.race_number for r, _ in race_predictions],
        "note_url":     "",
        "x_post":       "",
    }

    # ── 1会場まとめ記事を生成 ─────────────────────────────────
    article = article_gen.generate_venue(
        venue_config=venue_config,
        race_predictions=race_predictions,
    )
    logger.info(
        "[%s] 記事生成完了: %d文字 対象レース=%s",
        venue_name,
        len(article.full_md),
        [f"{r.race_number}R" for r, _ in race_predictions],
    )

    # ── Note 下書き保存 ───────────────────────────────────────
    body_html = markdown_to_note_html(article.full_md)

    if dry_run:
        logger.info("[DRY_RUN] Note下書きスキップ: %s", article.title)
        note_url = "https://note.com/notes/dry_run_dummy"
    else:
        # ステップ1: 下書き作成
        draft    = note_client.create_draft()
        note_id  = draft["id"]
        note_key = draft["key"]
        logger.info(
            "[%s] 下書き作成完了: id=%s key=%s",
            venue_name, note_id, note_key,
        )

        # ステップ2: 下書き保存（タイトル・本文のみ、価格は手動設定）
        note_client.save_draft(
            note_id=note_id,
            title=article.title,
            body_html=body_html,
        )
        note_url = f"https://note.com/notes/{note_key}"
        logger.info("[%s] Note下書き保存完了 → %s", venue_name, note_url)

    result["note_url"] = note_url

    # ── X 投稿文生成（最も信頼度の高いレースで代表生成） ─────
    best_race, best_pred = max(
        race_predictions,
        key=lambda rp: {"高": 3, "中": 2, "低": 1}.get(rp[1].confidence, 0),
    )
    x_post = x_gen.generate(
        prediction=best_pred,
        venue_config=venue_config,
        note_url=note_url,
    )
    result["x_post"] = x_post
    logger.info("[%s] X投稿文:\n%s", venue_name, x_post)

    # ── 評価記録 ──────────────────────────────────────────────
    for race, pred in race_predictions:
        try:
            evaluator.record(prediction=pred, race=race)
        except Exception as exc:  # noqa: BLE001
            logger.warning("評価記録失敗（無視）: %s", exc)

    return result


# ------------------------------------------------------------------ #
#  メインエントリーポイント                                            #
# ------------------------------------------------------------------ #

def main(
    target_date: date | None = None,
    dry_run: bool | None = None,
) -> list[dict]:
    """
    全対象会場の予想記事を生成・Note下書き保存する。

    Args:
        target_date: 対象日（デフォルト: 今日）
        dry_run    : True の場合 Note 投稿をスキップ
    Returns:
        処理結果のリスト
    """
    # ── 初期設定 ──────────────────────────────────────────────
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if target_date is None:
        target_date = date.today()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Windows CP932 環境での絵文字出力対策
    if sys.stdout.encoding and sys.stdout.encoding.lower() in ("cp932", "shift_jis", "shift-jis"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logger.info(
        "=== pipeline.main() 開始 date=%s dry_run=%s ===",
        target_date, dry_run,
    )

    # ── クライアント初期化 ────────────────────────────────────
    venues      = _load_venues()
    api         = BoatraceAPIClient(cache_dir=_DATA_RAW)
    note_client = NoteClient()
    note_client.login()
    article_gen = ArticleGenerator()
    x_gen       = XPostGenerator()
    evaluator   = Evaluator(results_dir=ROOT / "data" / "results")

    all_results: list[dict] = []
    errors:      list[str]  = []

    for venue_config in venues:
        stadium_number = venue_config.stadium_number
        logger.info(
            "--- 会場処理開始: %s (stadium=%d) ---",
            venue_config.name, stadium_number,
        )

        try:
            # ── 当日の出走表を取得 ────────────────────────────
            races = api.get_venue_races(target_date, stadium_number)
            if not races:
                logger.warning(
                    "%s: 当日(%s)データなし → スキップ",
                    venue_config.name, target_date,
                )
                continue

            # ── 対象レースを選択 ──────────────────────────────
            selected_races = _select_races(races)
            if not selected_races:
                logger.warning("%s: 対象レースなし → スキップ", venue_config.name)
                continue

            # ── 選択レースを全て予測 ──────────────────────────
            race_predictions: list[tuple] = []
            builder   = FeatureBuilder()
            predictor = RuleBasedPredictor()

            for race in selected_races:
                features = builder.build(race)
                pred     = predictor.predict(features)
                race_predictions.append((race, pred))
                logger.info(
                    "[%s %dR] 本命=%s 信頼度=%s",
                    race.venue_name, race.race_number,
                    pred.honmei.racer_name, pred.confidence,
                )

            # ── 1会場1記事で処理 ──────────────────────────────
            res = _process_venue(
                venue_config=venue_config,
                race_predictions=race_predictions,
                note_client=note_client,
                article_gen=article_gen,
                x_gen=x_gen,
                evaluator=evaluator,
                dry_run=dry_run,
            )
            all_results.append(res)

            # Note APIへの連続リクエストを避けるため少し待機
            time.sleep(2)

        except Exception as exc:  # noqa: BLE001
            msg = f"{venue_config.name} 処理失敗: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

    # ── 完了通知 ──────────────────────────────────────────────
    summary = (
        f"✅ pipeline完了: {len(all_results)}件投稿"
        + (f" ⚠️ {len(errors)}件エラー" if errors else "")
    )
    logger.info(summary)
    _notify_slack(summary + ("\n" + "\n".join(errors) if errors else ""))

    return all_results


# ------------------------------------------------------------------ #
#  スクリプト直接実行                                                  #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    results = main()
    for r in results:
        race_nums = "・".join(f"{n}R" for n in r["race_numbers"])
        print(f"\n【{r['venue']} {race_nums}】")
        print(f"  Note: {r['note_url']}")
        print(f"  X投稿文:\n{r['x_post']}")
