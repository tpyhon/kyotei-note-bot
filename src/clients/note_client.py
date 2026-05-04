# src/clients/note_client.py
"""
Note 非公式API クライアント

処理フロー:
  1. Cookie注入でログインを試みる（GitHub Actions用）
  2. 失敗時はメール/パスワードでフォールバック
  3. 下書き作成 → 本文保存 → 公開 の3ステップで記事を投稿
"""

import logging
import os
import uuid
import re
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# Markdown → Note HTML 変換
# ──────────────────────────────────────────

def markdown_to_note_html(text: str) -> str:
    """
    Markdown テキストを Note が受け付ける HTML 形式に変換する。

    対応記法:
      ## 見出し2  →  <h2>
      ### 見出し3 →  <h3>
      - / * リスト →  <ul><li>
      **太字**     →  <strong>
      空行         →  <br> 付き空段落
      それ以外     →  <p>
    """
    lines = text.split("\n")
    html_parts = []

    for line in lines:
        uid = str(uuid.uuid4())

        if not line.strip():
            html_parts.append(
                f'<p name="{uid}" id="{uid}"><br></p>'
            )
        elif line.startswith("## "):
            content = _inline(line[3:].strip())
            html_parts.append(
                f'<h2 name="{uid}" id="{uid}">{content}</h2>'
            )
        elif line.startswith("### "):
            content = _inline(line[4:].strip())
            html_parts.append(
                f'<h3 name="{uid}" id="{uid}">{content}</h3>'
            )
        elif line.startswith("- ") or line.startswith("* "):
            content = _inline(line[2:].strip())
            html_parts.append(
                f'<ul><li name="{uid}" id="{uid}">{content}</li></ul>'
            )
        else:
            content = _inline(line)
            html_parts.append(
                f'<p name="{uid}" id="{uid}">{content}</p>'
            )

    return "".join(html_parts)


def _inline(text: str) -> str:
    """インライン記法（太字・取り消し線）を HTML タグに変換する。"""
    # **太字**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # ~~取り消し線~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    return text


def _count_text_length(html: str) -> int:
    """HTML タグを除いた実文字数を返す（Note の body_length に使用）。"""
    return len(re.sub(r'<[^>]+>', '', html))


# ──────────────────────────────────────────
# 例外クラス
# ──────────────────────────────────────────

class NoteAuthError(Exception):
    """認証失敗時に送出する例外。"""


class NoteAPIError(Exception):
    """API 呼び出し失敗時に送出する例外。"""


# ──────────────────────────────────────────
# NoteClient
# ──────────────────────────────────────────

class NoteClient:
    """
    Note 非公式API を操作するクライアント。

    使い方:
        client = NoteClient()
        client.login(email, password)          # 認証
        draft = client.create_draft()          # 下書き作成
        client.save_draft(draft["id"], ...)    # 本文保存
        url = client.publish(draft["id"], ...) # 公開
    """

    BASE_URL     = "https://note.com/api/v1"
    _RETRY_COUNT = 3
    _RETRY_WAIT  = 2.0   # 秒

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://note.com/",
            "Origin":  "https://note.com",
        })
        # ログイン後に create_draft で取得した下書き情報をキャッシュ
        self._prefetched_draft: Optional[dict] = None

    # ──────────────────────────────────────
    # 公開メソッド
    # ──────────────────────────────────────

    def login(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        """
        認証を行う。

        優先順位:
          1. 環境変数 NOTE_SESSION_COOKIE が存在 → Cookie 注入
          2. 失敗時はメール/パスワードでフォールバック
          3. email / password 引数 → メール/パスワード認証
          4. 環境変数 NOTE_EMAIL / NOTE_PASSWORD → メール/パスワード認証
        """
        session_cookie = os.environ.get("NOTE_SESSION_COOKIE", "").strip()

        if session_cookie:
            logger.info("Cookie 注入でログインを試みます")
            if self._login_with_cookie(session_cookie):
                return
            logger.warning(
                "Cookie 注入に失敗しました。"
                "メール/パスワードでフォールバックします"
            )

        # メール/パスワード認証
        _email    = email    or os.environ.get("NOTE_EMAIL", "")
        _password = password or os.environ.get("NOTE_PASSWORD", "")

        if not _email or not _password:
            raise NoteAuthError(
                "NOTE_EMAIL / NOTE_PASSWORD が設定されていません"
            )

        self._login_with_password(_email, _password)

    def create_draft(self) -> dict:
        """
        新規下書きを作成する。

        Returns:
            {"id": int, "key": str}
        """
        # Cookie 注入ログイン時にプリフェッチ済みの場合はそれを返す
        if self._prefetched_draft:
            draft = self._prefetched_draft
            self._prefetched_draft = None
            logger.info(
                f"プリフェッチ済み下書きを使用: "
                f"id={draft['id']}, key={draft['key']}"
            )
            return draft

        resp = self._post(
            "/text_notes",
            json={"template_key": None},
        )
        raw  = resp.json()
        data = raw.get("data") or raw
        if isinstance(data, list):
            data = data[0] if data else {}

        draft = {"id": data["id"], "key": data["key"]}
        logger.info(
            f"下書き作成完了: id={draft['id']}, key={draft['key']}"
        )
        return draft

    def save_draft(
        self,
        note_id: int,
        title: str,
        body_html: str,
    ) -> None:
        """
        下書きの本文を中間保存する（is_temp_saved=true）。

        Args:
            note_id:   create_draft() で取得した id
            title:     記事タイトル
            body_html: markdown_to_note_html() で変換済みの HTML
        """
        payload = {
            "name":         title,
            "body":         body_html,
            "body_length":  _count_text_length(body_html),
            "index":        False,
            "is_lead_form": False,
        }
        self._post(
            f"/text_notes/draft_save?id={note_id}&is_temp_saved=true",
            json=payload,
        )
        logger.info(f"下書き保存完了: id={note_id}")

    def publish(
        self,
        note_id: int,
        note_key: str,
        title: str,
        body_html: str,
        hashtags: list[str],
        price: int = 500,
    ) -> str:
        """
        記事を公開する（is_temp_saved=false, publish=true）。

        Args:
            note_id:   create_draft() で取得した id
            note_key:  create_draft() で取得した key
            title:     記事タイトル
            body_html: markdown_to_note_html() で変換済みの HTML
            hashtags:  タグのリスト（# なし）
            price:     販売価格（円）。0 で無料記事。

        Returns:
            公開済み記事の URL  例) https://note.com/notes/nXXXXXXXXXXXX
        """
        payload = {
            "name":         title,
            "body":         body_html,
            "body_length":  _count_text_length(body_html),
            "price":        price,
            "hashtag_list": hashtags,
            "index":        True,
            "is_lead_form": False,
            "publish":      True,
            "status":       "published",
        }
        self._post(
            f"/text_notes/draft_save?id={note_id}&is_temp_saved=false",
            json=payload,
        )
        url = f"https://note.com/notes/{note_key}"
        logger.info(f"記事公開完了: {url}")
        return url

    # ──────────────────────────────────────
    # 内部ヘルパー
    # ──────────────────────────────────────

    def _login_with_cookie(self, session_cookie: str) -> bool:
        """
        _note_session_v5 Cookie を直接注入してログイン状態を確認する。
        下書き作成 API を呼んで成否を判定し、成功時はレスポンスをキャッシュ。

        ※ Note は認証失敗でも HTTP 201 を返し、
          ボディに {'error': {'code': 'auth', ...}} を含む仕様。
          そのため status_code だけでなく error キーの有無で判定する。

        Returns:
            True: 成功 / False: 失敗
        """
        self.session.cookies.clear()
        self.session.cookies.set(
            "_note_session_v5",
            session_cookie,
            domain=".note.com",
        )
        try:
            resp = self.session.post(
                f"{self.BASE_URL}/text_notes",
                json={"template_key": None},
                timeout=15,
            )

            logger.debug(f"status : {resp.status_code}")
            try:
                body = resp.json()
                logger.debug(f"body   : {body}")
            except Exception:
                logger.debug(f"body(raw): {resp.text[:500]}")
                body = {}

            # ── HTTP レベルの失敗 ──────────────────────────
            if resp.status_code not in (200, 201):
                logger.warning(
                    f"Cookie 注入: ステータスコード {resp.status_code}"
                )
                return False

            # ── Note 独自の認証失敗判定 ────────────────────
            # 認証失敗時は 201 で {'error': {'code': 'auth', ...}} が返る
            if "error" in body:
                error_info = body["error"]
                logger.warning(
                    f"Cookie 注入: 認証エラー "
                    f"code={error_info.get('code')}, "
                    f"message={error_info.get('message')}"
                )
                return False

            # ── レスポンスから id / key を取得 ────────────
            data = body.get("data") or body
            if isinstance(data, list):
                data = data[0] if data else {}

            note_id  = data.get("id")
            note_key = data.get("key")

            if not note_id:
                logger.warning(
                    f"Cookie 注入: レスポンスに 'id' が見つかりません。"
                    f"raw={body}"
                )
                return False

            self._prefetched_draft = {
                "id":  note_id,
                "key": note_key,
            }
            logger.info(
                f"Cookie 注入ログイン成功: id={note_id}, key={note_key}"
            )
            return True

        except requests.RequestException as e:
            logger.warning(f"Cookie 注入中にエラー: {e}")
            return False


    def _login_with_password(self, email: str, password: str) -> None:
        """
        メールアドレスとパスワードで Note にログインする。
        成功するとセッション Cookie が自動的に保持される。
        """
        resp = self._post(
            "/sessions/sign_in",
            json={
                "login":         email,
                "password":      password,
                "redirect_path": "",
            },
        )
        if resp.status_code not in (200, 201):
            raise NoteAuthError(
                f"ログイン失敗: status={resp.status_code}, "
                f"body={resp.text[:200]}"
            )
        logger.info("メール/パスワードログイン成功")

    def _post(
        self,
        path: str,
        json: Optional[dict] = None,
        retry: int = _RETRY_COUNT,
    ) -> requests.Response:
        """
        POST リクエストを送信する共通メソッド。
        5xx エラー・タイムアウト時はリトライする。

        ※ Note は成功・失敗ともに 200/201 を返す場合があるため、
          ボディの error キー有無も合わせて判定する。

        Args:
            path:  BASE_URL からの相対パス（先頭 / あり）
            json:  リクエストボディ（dict）
            retry: リトライ残回数

        Returns:
            requests.Response

        Raises:
            NoteAPIError: リトライ上限超過 or クライアントエラー
        """
        url = f"{self.BASE_URL}{path}"
        for attempt in range(1, retry + 1):
            try:
                resp = self.session.post(
                    url,
                    json=json,
                    timeout=20,
                )

                # 4xx はリトライしない（認証エラー等）
                if 400 <= resp.status_code < 500:
                    raise NoteAPIError(
                        f"クライアントエラー: status={resp.status_code}, "
                        f"url={url}, body={resp.text[:300]}"
                    )

                # 5xx はリトライ
                if resp.status_code >= 500:
                    logger.warning(
                        f"サーバーエラー (attempt {attempt}/{retry}): "
                        f"status={resp.status_code}, url={url}"
                    )
                    if attempt < retry:
                        time.sleep(self._RETRY_WAIT * attempt)
                    continue

                # 200/201 でもボディに error が含まれる場合は失敗扱い
                # ただし sign_in と Cookie 注入チェックは呼び元で判定するため
                # ここでは sessions パスのみスキップ
                if resp.status_code in (200, 201):
                    try:
                        body = resp.json()
                        if "error" in body and "/sessions/" not in path:
                            raise NoteAPIError(
                                f"APIエラー: url={url}, "
                                f"error={body['error']}"
                            )
                    except (ValueError, KeyError):
                        pass  # JSON でない or error キーなし → 正常
                    return resp

            except requests.Timeout:
                logger.warning(
                    f"タイムアウト (attempt {attempt}/{retry}): url={url}"
                )
            except requests.ConnectionError as e:
                logger.warning(
                    f"接続エラー (attempt {attempt}/{retry}): {e}"
                )

            if attempt < retry:
                time.sleep(self._RETRY_WAIT * attempt)

        raise NoteAPIError(
            f"リトライ上限超過: url={url}"
        )



# ──────────────────────────────────────────
# スタンドアロン実行（動作確認用）
# ──────────────────────────────────────────

def main(
    title: str = "テスト記事【波乃みなとの競艇GOGO！】",
    body_md: str = "## 今日の予想\n\nテスト本文です。\n\n**注目レース**：第8R",
    hashtags: list[str] = None,
    price: int = 500,
) -> str:
    """
    Note に記事を1件投稿して URL を返す。
    """
    if hashtags is None:
        hashtags = ["競艇", "競艇予想", "ボートレース"]

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    body_html = markdown_to_note_html(body_md)
    logger.info(f"HTML変換完了: {len(body_html)} 文字")

    client = NoteClient()

    # 1. ログイン
    client.login()

    # 2. 下書き作成
    draft = client.create_draft()

    # 3. 中間保存
    client.save_draft(draft["id"], title, body_html)

    # 4. 公開
    url = client.publish(
        note_id=draft["id"],
        note_key=draft["key"],
        title=title,
        body_html=body_html,
        hashtags=hashtags,
        price=price,
    )

    return url


if __name__ == "__main__":
    result_url = main()
    print(f"\n✅ 投稿完了: {result_url}")
