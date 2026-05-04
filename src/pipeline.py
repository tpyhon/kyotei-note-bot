"""
メインパイプライン – データ取得 → 予測 → 記事生成 → Note投稿 → X投稿文出力
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# ── .env 読み込み（GitHub Actions では環境変数として注入される）────
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

ROOT = Path(__file__).resolve().parent.parent
_VENUES_CFG = ROOT / "config" / "venues.yml"
_DATA_RAW = ROOT / "data" / "raw"


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
#  1会場・1レース分の処理                                              #
# ------------------------------------------------------------------ #

def _process_race(
    race,
    venue_config: VenueConfig,
    note_client: NoteClient,
    article_gen: ArticleGenerator,
    x_gen: XPostGenerator,
    evaluator: Evaluator,
    dry_run: bool,
) -> dict:
    """
    1レース分のパイプラインを実行し、結果辞書を返す。
    戻り値: {"venue": str, "race_number": int, "note_url": str, "x_post": str}
    """
    result = {
        "venue": race.venue_name,
        "race_number": race.race_number,
        "note_url": "",
        "x_post": "",
    }

    # ── 予測 ──────────────────────────────────────────────────────
    builder = FeatureBuilder()
    features = builder.build(race)
    predictor = RuleBasedPredictor()
    prediction = predictor.predict(features)
    logger.info(
        "[%s %dR] 本命=%s 信頼度=%s",
        race.venue_name, race.race_number,
        prediction.honmei.racer_name, prediction.confidence,
    )

    # ── 記事生成 ──────────────────────────────────────────────────
    article = article_gen.generate(race=race, prediction=prediction)
    logger.info("[%s %dR] 記事生成完了: %d文字", race.venue_name, race.race_number, len(article.full_md))

    # ── Note 投稿 ─────────────────────────────────────────────────
    body_html = markdown_to_note_html(article.full_md)

    if dry_run:
        logger.info("[DRY_RUN] Note投稿スキップ: %s", article.title)
        note_url = "https://note.com/notes/dry_run_dummy"
    else:
        # ステップ1: 下書き作成 → note_id と note_key を取得
        draft = note_client.create_draft()
        note_id = draft["id"]
        note_key = draft["key"]
        logger.info(
            "[%s %dR] 下書き作成完了: id=%s key=%s",
            race.venue_name, race.race_number, note_id, note_key,
        )

        # ステップ2: 下書き一時保存
        note_client.save_draft(
            note_id=note_id,
            title=article.title,
            body_html=body_html,
        )
        logger.info("[%s %dR] 下書き保存完了", race.venue_name, race.race_number)

        # ステップ3: 公開
        note_url = note_client.publish(
            note_id=note_id,
            note_key=note_key,
            title=article.title,
            body_html=body_html,
            hashtags=article.hashtags,
            price=article.price,
        )
        logger.info(
            "[%s %dR] Note投稿完了: %s",
            race.venue_name, race.race_number, note_url,
        )


    # ── X 投稿文生成 ──────────────────────────────────────────────
    x_post = x_gen.generate(
        prediction=prediction,
        venue_config=venue_config,
        note_url=note_url,
    )
    result["x_post"] = x_post
    logger.info("[%s %dR] X投稿文:\n%s", race.venue_name, race.race_number, x_post)

    # ── 評価記録（前日結果があれば） ──────────────────────────────
    try:
        evaluator.record(prediction=prediction, race=race)
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
    全対象会場のレース予想記事を生成・投稿する。

    Args:
        target_date: 対象日（デフォルト: 今日）
        dry_run    : True の場合 Note 投稿をスキップ（デフォルト: 環境変数 DRY_RUN）
    Returns:
        処理結果のリスト
    """
    # ── 設定 ──────────────────────────────────────────────────────
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if target_date is None:
        target_date = date.today()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("=== pipeline.main() 開始 date=%s dry_run=%s ===", target_date, dry_run)

    venues = _load_venues()
    api = BoatraceAPIClient(cache_dir=_DATA_RAW)
    note_client = NoteClient()
    note_client.login()
    article_gen = ArticleGenerator()
    x_gen = XPostGenerator()
    evaluator = Evaluator(results_dir=ROOT / "data" / "results")

    all_results: list[dict] = []
    errors: list[str] = []

    for venue_config in venues:
        stadium_number = venue_config.stadium_number
        logger.info("--- 会場処理開始: %s (stadium=%d) ---", venue_config.name, stadium_number)

        try:
            # 当日の出走表を取得（なければ前日）
            races = api.get_venue_races(target_date, stadium_number)
            if not races:
                races = api.get_venue_races(target_date - timedelta(days=1), stadium_number)
            if not races:
                logger.warning("%s: レースデータなし → スキップ", venue_config.name)
                continue

            # メインレース（最終レース or 指定レース）を選択
            # ここでは全レースの中から最も注目度の高いレース（後半レース）を選択
            target_race_number = int(os.environ.get("TARGET_RACE_NUMBER", "0"))
            if target_race_number > 0:
                race = next((r for r in races if r.race_number == target_race_number), races[-1])
            else:
                # デフォルト: レース番号が最も大きいもの（最終レース付近）
                race = max(races, key=lambda r: r.race_number)

            res = _process_race(
                race=race,
                venue_config=venue_config,
                note_client=note_client,
                article_gen=article_gen,
                x_gen=x_gen,
                evaluator=evaluator,
                dry_run=dry_run,
            )
            all_results.append(res)

        except Exception as exc:  # noqa: BLE001
            msg = f"{venue_config.name} 処理失敗: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

    # ── 完了通知 ──────────────────────────────────────────────────
    summary = (
        f"✅ pipeline完了: {len(all_results)}件投稿"
        + (f" ⚠️ {len(errors)}件エラー" if errors else "")
    )
    logger.info(summary)
    _notify_slack(summary + ("\n" + "\n".join(errors) if errors else ""))

    return all_results


if __name__ == "__main__":
    results = main()
    for r in results:
        print(f"\n【{r['venue']} {r['race_number']}R】")
        print(f"  Note: {r['note_url']}")
        print(f"  X投稿文:\n{r['x_post']}")
