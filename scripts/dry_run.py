# scripts/dry_run.py
"""
実際の投稿はせずに、記事の生成・HTML変換・ログ出力だけを行う動作確認スクリプト。

使い方:
    python scripts/dry_run.py
"""

import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.clients.note_client import markdown_to_note_html, _count_text_length

logging.basicConfig(
    level="INFO",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dry_run")


# ── テスト用サンプル記事 ──────────────────────────────────

SAMPLE_TITLE = "【2026/05/04】ボートレース大村 第8R 本日の予想｜波乃みなとの競艇GOGO！"

SAMPLE_BODY_MD = """\
## 🌊 今日もみなとと一緒に舟券を楽しもう！

こんにちは、波乃みなとです⚓

本日のボートレース大村、注目レースは **第8R** です！
データを見れば見るほどアツいレースになりそうな予感…🔥

昨日の結果：**3連単 1-3-2 的中！** 払戻 2,480円 ✨

---

※ ここから先は有料部分です ※

## 📊 データ根拠

今節の注目選手はこちらです。

- **1号艇 山田 太郎**（A1級）：当場勝率 7.82、今節モーター2連率 68.3%
- **3号艇 鈴木 花子**（A2級）：スタートタイミング平均 0.11秒

**モーター成績（2連率）** 今節上位3機：
- 32号機：68.3%
- 17号機：61.2%
- 08号機：58.7%

大村は防風ネット設置で **風の影響が極小**。
インコース1着率 **62.7%** と全国トップクラス。
今節後半・7〜12Rはさらにイン1着率が 6% 上昇する傾向あり。

## 🎯 本日の予想

**本命（軸）**：1号艇 山田 太郎
**対抗**：3号艇 鈴木 花子 / 2号艇 田中 次郎
**穴**：4号艇 佐藤 三郎（スタートが決まれば一発あり）

## 🛒 買い目

3連単（本線3点）
- 1-3-2 ：本命ライン
- 1-2-3 ：対抗ライン
- 1-3-4 ：穴含み

2連単（保険2点）
- 1-3
- 1-2

**想定投資：1点500円 × 5点 = 2,500円**

## 🌊 みなとの一言

山田選手、今節ずっと安定してるんです！
モーターも68%超えで今節ベスト級。
大村のナイターは風も穏やか、絶好の逃げ条件です🚤
みんなで応援しながら楽しみましょう～！
"""

SAMPLE_HASHTAGS = ["競艇", "ボートレース大村", "競艇予想", "大村競艇", "波乃みなと"]
SAMPLE_PRICE    = 500


def main():
    logger.info("=" * 55)
    logger.info("  DRY RUN モード（実際の投稿は行いません）")
    logger.info("=" * 55)

    # ── 1. Markdown → HTML 変換 ──────────────────────────
    logger.info("\n[STEP 1] Markdown → HTML 変換")
    body_html = markdown_to_note_html(SAMPLE_BODY_MD)
    char_count = _count_text_length(body_html)

    logger.info(f"  タイトル     : {SAMPLE_TITLE}")
    logger.info(f"  HTML文字数   : {len(body_html)}")
    logger.info(f"  本文文字数   : {char_count}")
    logger.info(f"  ハッシュタグ : {SAMPLE_HASHTAGS}")
    logger.info(f"  価格         : {SAMPLE_PRICE}円")

    # ── 2. HTML の先頭だけプレビュー ─────────────────────
    logger.info("\n[STEP 2] 生成 HTML プレビュー（先頭500文字）")
    print("-" * 55)
    print(body_html[:500])
    print("...")
    print("-" * 55)

    # ── 3. 投稿ペイロードの確認 ─────────────────────────
    logger.info("\n[STEP 3] publish() に渡されるペイロード（確認用）")
    payload = {
        "name":         SAMPLE_TITLE,
        "body_length":  char_count,
        "price":        SAMPLE_PRICE,
        "hashtag_list": SAMPLE_HASHTAGS,
        "index":        True,
        "publish":      True,
        "status":       "published",
    }
    for k, v in payload.items():
        logger.info(f"  {k:<15}: {v}")

    logger.info("\n✅ DRY RUN 完了。内容に問題がなければ実投稿を行ってください。")
    logger.info("   実投稿: python -c \"from src.clients.note_client import main; print(main())\"")


if __name__ == "__main__":
    main()
