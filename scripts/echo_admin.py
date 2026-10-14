"""Operator tool for a hosted Echo server: accounts and minutes.

Run on the server with the same ECHO_DATA_DIR as the service, e.g.

    ECHO_DATA_DIR=/srv/echo/data backend/.venv/bin/python scripts/echo_admin.py list
    ... add 1203 --password 123456 --minutes 300
    ... grant 1203 --minutes 600 --note "10月 微信转账 ¥49"
    ... disable 1203 / enable 1203
    ... passwd 1203 --password newpass
    ... add-admin boss --password <strong password>

Accounts without "@" are stored as <name>@echo.local; neighbours log in with
the short name.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from services import hosted_mode  # noqa: E402
from services.billing_service import billing_service  # noqa: E402
from services.user_auth_service import user_auth_service  # noqa: E402


def _minutes(seconds: int) -> str:
    return f"{seconds / 60:.1f}"


def cmd_list(args: argparse.Namespace) -> None:
    since = int(time.time()) - args.days * 86400
    usage = {row["user_email"]: row for row in billing_service.usage_summary(since=since)}
    print(f"{'账号':<16}{'状态':<6}{'剩余(分)':>10}{f'近{args.days}天用(分)':>14}  最近使用")
    for user in user_auth_service.list_users():
        email = str(user["email"])
        row = usage.get(email, {})
        last = row.get("last_used_at")
        status = "管理员" if user["is_admin"] else ("正常" if user["is_active"] else "停用")
        print(
            f"{hosted_mode.display_account_id(email):<16}{status:<6}"
            f"{_minutes(int(row.get('balance_seconds', 0))):>10}"
            f"{_minutes(int(row.get('used_seconds', 0))):>14}  "
            f"{datetime.fromtimestamp(last).strftime('%m-%d %H:%M') if last else '-'}"
        )
    by_model = billing_service.usage_by_model(since=since)
    if by_model:
        print(f"\n按模型（近{args.days}天，实际通话分钟）:")
        for row in by_model:
            print(f"  {row['provider']:<10}{row['model']:<45}{_minutes(row['wall_seconds']):>8}")


def _create(account: str, password: str, minutes: int, *, admin: bool) -> None:
    email = hosted_mode.normalize_account_id(account)
    if admin and user_auth_service.has_users():
        sys.exit("已有账号；管理员只能是第一个创建的账号。")
    if not admin and not user_auth_service.has_users():
        sys.exit("请先用 add-admin 创建管理员账号（第一个账号自动成为管理员）。")
    user_auth_service.register_user(email, password)
    if minutes:
        billing_service.grant(email, minutes * 60, note="initial")
    print(f"已创建 {account}，剩余 {billing_service.get_balance(email) // 60} 分钟")


def cmd_add(args: argparse.Namespace) -> None:
    _create(args.account, args.password, args.minutes, admin=False)


def cmd_add_admin(args: argparse.Namespace) -> None:
    _create(args.account, args.password, 0, admin=True)


def cmd_grant(args: argparse.Namespace) -> None:
    email = hosted_mode.normalize_account_id(args.account)
    if email not in {str(u["email"]) for u in user_auth_service.list_users()}:
        sys.exit(f"找不到账号 {args.account}")
    balance = billing_service.grant(email, args.minutes * 60, note=args.note)
    print(f"{args.account} 现在剩余 {_minutes(balance)} 分钟")


def cmd_active(args: argparse.Namespace, active: bool) -> None:
    user_auth_service.set_active(hosted_mode.normalize_account_id(args.account), active)
    print(f"{args.account} 已{'启用' if active else '停用'}")


def cmd_passwd(args: argparse.Namespace) -> None:
    user_auth_service.set_password(hosted_mode.normalize_account_id(args.account), args.password)
    print(f"{args.account} 密码已重置（已登录的设备需要重新登录）")


def main() -> None:
    parser = argparse.ArgumentParser(description="Echo 托管版账号与时长管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="列出账号、余额和用量")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add", help="新建用户账号")
    p.add_argument("account")
    p.add_argument("--password", required=True)
    p.add_argument("--minutes", type=int, default=0)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("add-admin", help="新建管理员（只能是第一个账号）")
    p.add_argument("account")
    p.add_argument("--password", required=True)
    p.set_defaults(func=cmd_add_admin)

    p = sub.add_parser("grant", help="增加（或用负数扣减）分钟数")
    p.add_argument("account")
    p.add_argument("--minutes", type=int, required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_grant)

    p = sub.add_parser("disable", help="停用账号")
    p.add_argument("account")
    p.set_defaults(func=lambda a: cmd_active(a, False))

    p = sub.add_parser("enable", help="启用账号")
    p.add_argument("account")
    p.set_defaults(func=lambda a: cmd_active(a, True))

    p = sub.add_parser("passwd", help="重置密码")
    p.add_argument("account")
    p.add_argument("--password", required=True)
    p.set_defaults(func=cmd_passwd)

    args = parser.parse_args()
    try:
        args.func(args)
    except ValueError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
