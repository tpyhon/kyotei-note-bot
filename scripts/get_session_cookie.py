# scripts/get_session_cookie.py
"""
ローカル環境で Note にログインし、
GitHub Secrets に登録する _note_session_v5 の値を取得・表示する。

使い方:
    python scripts/get_session_cookie.py
"""

import os
import sys
import getpass

import requests
from dotenv import load_dotenv

# プロジェクトルートを sys.path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()


def get_session_cookie(email: str, password: str) -> str:
    """
    Note にメール/パスワードでログインし、
    _note_session_v5 Cookie の値を返す。
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://note.com/",
        "Origin":  "https://note.com",
    })

    resp = session.post(
        "https://note.com/api/v1/sessions/sign_in",
        json={
            "login":         email,
            "password":      password,
            "redirect_path": "",
        },
        timeout=20,
    )

    if resp.status_code not in (200, 201):
        print(f"❌ ログイン失敗: status={resp.status_code}")
        print(f"   レスポンス: {resp.text[:300]}")
        sys.exit(1)

    cookie_value = session.cookies.get("_note_session_v5", domain=".note.com")

    if not cookie_value:
        # ドメイン指定なしでも探す
        for cookie in session.cookies:
            if cookie.name == "_note_session_v5":
                cookie_value = cookie.value
                break

    if not cookie_value:
        print("❌ _note_session_v5 Cookie が見つかりませんでした")
        print("   取得できた Cookie 一覧:")
        for c in session.cookies:
            print(f"     {c.name} = {c.value[:30]}...")
        sys.exit(1)

    return cookie_value


def main():
    print("=" * 60)
    print("  Note セッション Cookie 取得ツール")
    print("=" * 60)

    # .env から読む、なければ対話入力
    email    = os.environ.get("NOTE_EMAIL", "")
    password = os.environ.get("NOTE_PASSWORD", "")

    if not email:
        email = input("Note メールアドレス: ").strip()
    else:
        print(f"NOTE_EMAIL を使用: {email}")

    if not password:
        password = getpass.getpass("Note パスワード: ")
    else:
        print("NOTE_PASSWORD を使用: （.env から読み込み済み）")

    print("\nログイン中...")
    cookie = get_session_cookie(email, password)

    print("\n" + "=" * 60)
    print("✅ 取得成功！以下の値を GitHub Secrets に登録してください")
    print("=" * 60)
    print(f"\nSecret名 : NOTE_SESSION_COOKIE")
    print(f"値       : {cookie}")
    print("\n" + "=" * 60)
    print("⚠️  この値は認証情報です。絶対に .env 以外には保存しないでください")
    print("=" * 60)


if __name__ == "__main__":
    main()
