"""
Note API クライアント（非公式）
requests のみ使用・GitHub Actions 対応版
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://note.com"


# ------------------------------------------------------------------ #
#  例外クラス                                                          #
# ------------------------------------------------------------------ #

class NoteAuthError(Exception):
    pass


class NoteAPIError(Exception):
    pass


# ------------------------------------------------------------------ #
#  Markdown → Note HTML 変換                                          #
# ------------------------------------------------------------------ #

def markdown_to_note_html(text: str) -> str:
    lines = text.split("\n")
    html_parts = []

    for line in lines:
        uid = str(uuid.uuid4())

        if not line.strip():
            html_parts.append(f'<p name="{uid}" id="{uid}"><br></p>')
        elif line.startswith("## "):
            content = _inline(line[3:].strip())
            html_parts.append(f'<h2 name="{uid}" id="{uid}">{content}</h2>')
        elif line.startswith("### "):
            content = _inline(line[4:].strip())
            html_parts.append(f'<h3 name="{uid}" id="{uid}">{content}</h3>')
        elif line.startswith("- ") or line.startswith("* "):
            content = _inline(line[2:].strip())
            html_parts.append(f'<ul><li name="{uid}" id="{uid}">{content}</li></ul>')
        else:
            content = _inline(line)
            html_parts.append(f'<p name="{uid}" id="{uid}">{content}</p>')

    return "".join(html_parts)


def _inline(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    return text


def _count_text_length(html: str) -> int:
    clean = re.sub(r'<[^>]+>', '', html)
    return len(clean)


# ------------------------------------------------------------------ #
#  NoteClient                                                          #
# ------------------------------------------------------------------ #

class NoteClient:

    TIMEOUT = 30
    RETRY_COUNT = 3
    RETRY_WAIT = 2

    def __init__(self) -> None:
        self.session = requests.Session()
        self._prefetched_draft: Optional[dict] = None
        # ── GitHub Actions でも確実に動作するヘッダー ──────────────
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer":      "https://note.com/",
            "Origin":       "https://note.com",
            "Content-Type": "application/json",
            "Accept":       "application/json, text/plain, */*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        })

    # ---------------------------------------------------------------- #
    #  ログイン                                                          #
    # ---------------------------------------------------------------- #

    def login(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        email    = email    or os.environ.get("NOTE_EMAIL", "")
        password = password or os.environ.get("NOTE_PASSWORD", "")

        # ── Cookie注入を試みる ──────────────────────────────────────
        session_cookie = os.environ.get("NOTE_SESSION_COOKIE", "")
        if session_cookie and self._login_with_cookie(session_cookie):
            return

        logger.warning("Cookie注入失敗 → メール/パスワードでフォールバック")

        # ── メール/パスワードログイン ──────────────────────────────
        if not email or not password:
            raise NoteAuthError("NOTE_EMAIL / NOTE_PASSWORD が設定されていません")

        self._login_with_password(email, password)

    def _login_with_cookie(self, session_cookie: str) -> bool:
        logger.info("Cookie 注入でログインを試みます")
        self.session.cookies.clear()
        self.session.cookies.set(
            "_note_session_v5",
            session_cookie,
            domain=".note.com",
        )
        # 下書き作成でセッション確認
        resp = self.session.post(
            f"{BASE_URL}/api/v1/text_notes",
            json={"template_key": None},
            timeout=self.TIMEOUT,
        )
        logger.debug("Cookie確認レスポンス: status=%d body=%s", resp.status_code, resp.text[:200])

        if resp.status_code in (200, 201):
            body = resp.json()
            data = body.get("data", body)
            if "error" in data or "id" not in data:
                logger.warning("Cookie注入: 認証エラー %s", data.get("error", data))
                return False
            self._prefetched_draft = data
            logger.info("Cookie認証成功・下書き作成済み: id=%s", data.get("id"))
            return True

        logger.warning("Cookie注入: status=%d", resp.status_code)
        return False

    def _login_with_password(self, email: str, password: str) -> None:
        logger.info("メール/パスワードでログイン中...")
        resp = self.session.post(
            f"{BASE_URL}/api/v1/sessions/sign_in",
            json={
                "login":         email,
                "password":      password,
                "redirect_path": "",
            },
            timeout=self.TIMEOUT,
        )
        logger.debug(
            "ログインレスポンス: status=%d body=%s",
            resp.status_code, resp.text[:300],
        )
        if resp.status_code not in (200, 201):
            raise NoteAuthError(f"ログイン失敗: status={resp.status_code}")

        body = resp.json()
        if "error" in body:
            raise NoteAuthError(f"ログインエラー: {body['error']}")

        # Cookie確認・ログ出力
        cookies = dict(self.session.cookies)
        session_keys = [k for k in cookies if "session" in k.lower()]
        logger.debug("取得したCookieキー: %s", session_keys)

        if not session_keys:
            logger.warning(
                "セッションCookieが取得できていません。"
                "NOTE_SESSION_COOKIE の更新が必要な可能性があります。"
            )

        # 新しいセッションCookieをログ出力（GitHub Secretsの更新案内）
        new_cookie = self.session.cookies.get("_note_session_v5", "")
        if new_cookie:
            logger.info(
                "新しいセッションCookie取得完了。"
                "GitHub Secrets の NOTE_SESSION_COOKIE を以下の値で更新すると"
                "次回からCookie認証が使えます: %s...（先頭20文字）",
                new_cookie[:20],
            )

        logger.info("メール/パスワードログイン成功")

    # ---------------------------------------------------------------- #
    #  下書き作成                                                        #
    # ---------------------------------------------------------------- #

    def create_draft(self) -> dict:
        # login()でCookie認証済みの場合は使い回す
        if self._prefetched_draft:
            logger.info("既存下書きを使用: id=%s", self._prefetched_draft.get("id"))
            draft = self._prefetched_draft
            self._prefetched_draft = None
            return draft

        logger.info("下書き記事を新規作成...")
        resp = self.session.post(
            f"{BASE_URL}/api/v1/text_notes",
            json={"template_key": None},
            timeout=self.TIMEOUT,
        )
        logger.debug("create_draft: status=%d body=%s", resp.status_code, resp.text[:300])

        if resp.status_code not in (200, 201):
            raise NoteAPIError(f"下書き作成失敗: status={resp.status_code} body={resp.text[:200]}")

        body = resp.json()
        data = body.get("data", body)

        if "error" in data:
            raise NoteAPIError(f"下書き作成エラー: {data['error']}")
        if "id" not in data:
            raise NoteAPIError(f"予期しないレスポンス: {body}")

        logger.info("下書き作成完了: id=%s key=%s", data["id"], data["key"])
        return {"id": data["id"], "key": data["key"]}

    # ---------------------------------------------------------------- #
    #  下書き保存                                                        #
    # ---------------------------------------------------------------- #

    def save_draft(
        self,
        note_id: int,
        title: str,
        body_html: str,
    ) -> None:
        logger.info("下書き保存中: id=%s", note_id)
        resp = self.session.post(
            f"{BASE_URL}/api/v1/text_notes/draft_save",
            params={
                "id":            note_id,
                "is_temp_saved": "true",
            },
            json={
                "name":         title,
                "body":         body_html,
                "body_length":  len(body_html),
                "index":        False,
                "is_lead_form": False,
            },
            timeout=self.TIMEOUT,
        )
        if resp.status_code not in (200, 201):
            raise NoteAPIError(
                f"下書き保存失敗: status={resp.status_code} body={resp.text[:200]}"
            )
        logger.info("下書き保存完了")

    # ---------------------------------------------------------------- #
    #  公開                                                              #
    # ---------------------------------------------------------------- #

    def publish(
        self,
        note_id: int,
        note_key: str,
        title: str,
        body_html: str,
        hashtags: list[str],
        price: int = 500,
    ) -> str:
        logger.info("記事を公開中: id=%s", note_id)
        resp = self.session.post(
            f"{BASE_URL}/api/v1/text_notes/draft_save",
            params={
                "id":            note_id,
                "is_temp_saved": "false",
            },
            json={
                "name":         title,
                "body":         body_html,
                "body_length":  len(body_html),
                "price":        price,
                "hashtag_list": hashtags,
                "index":        True,
                "is_lead_form": False,
                "publish":      True,
                "status":       "published",
            },
            timeout=self.TIMEOUT,
        )
        if resp.status_code not in (200, 201):
            raise NoteAPIError(
                f"公開失敗: status={resp.status_code} body={resp.text[:300]}"
            )
        article_url = f"https://note.com/notes/{note_key}"
        logger.info("公開完了: %s", article_url)
        return article_url


# ------------------------------------------------------------------ #
#  動作テスト用 main                                                   #
# ------------------------------------------------------------------ #

def main() -> Optional[str]:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    test_md = """## テスト記事

これは **NoteClient** の動作テストです。

### 買い目

- 3連単 1-2-3
- 2連単 1-2

波乃みなとの競艇GOGO! のテスト投稿です。
"""
    body_html = markdown_to_note_html(test_md)
    logger.info("HTML変換完了: %d文字", len(body_html))

    client = NoteClient()
    client.login()

    draft = client.create_draft()
    note_id  = draft["id"]
    note_key = draft["key"]

    client.save_draft(note_id=note_id, title="【テスト】波乃みなと 動作確認", body_html=body_html)
    time.sleep(1)

    url = client.publish(
        note_id=note_id,
        note_key=note_key,
        title="【テスト】波乃みなと 動作確認",
        body_html=body_html,
        hashtags=["競艇", "競艇予想", "ボートレース"],
        price=500,
    )
    logger.info("投稿完了: %s", url)
    return url


if __name__ == "__main__":
    print(main())
