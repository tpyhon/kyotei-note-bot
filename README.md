# 競艇予測Note自動投稿Bot
**波乃みなとの競艇GOGO！**

競艇予測記事をAIで自動生成し、Noteに毎日投稿するプロジェクトです。

## 対象競艇場
- ボートレース大村
- ボートレース住之江
- ボートレース下関

## 技術スタック
- Python 3.11+
- Gemini API (gemma-4-26b-a4b-it)
- BoatraceOpenAPI
- GitHub Actions (毎日自動実行)
- Note 非公式API

## セットアップ
1. .env.example を .env にコピーして各値を設定
2. pip install -r requirements.txt
3. python scripts/get_session_cookie.py でNoteのセッションCookieを取得
4. GitHub Secretsに環境変数を登録

## ローカル動作確認
python scripts/dry_run.py

## ディレクトリ構成
詳細は設計ドキュメントを参照。
