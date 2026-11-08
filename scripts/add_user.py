"""关闭注册（REGISTRATION=closed）时，在服务器上手动建账号。和网页注册一样，新账号自带两位官方角色。

    cd ~/krino-world/app/backend && set -a && . ../../.env && set +a
    PYTHONPATH=. ../../.venv/bin/python ../../scripts/add_user.py 用户名 [密码]

不给密码就随机生成一个并打印出来。
"""
import secrets
import sys

from sqlalchemy import select

from app.auth import _USERNAME_RE, hash_password
from app.db import SessionLocal
from app.models import User
from app.personas import adopt_officials


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    name = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(9)
    if not _USERNAME_RE.match(name):
        sys.exit("用户名需 2-32 位字母、数字、下划线或中文")
    if len(password) < 6:
        sys.exit("密码至少 6 位")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == name)):
            sys.exit(f"用户名已存在：{name}")
        user = User(username=name, password_hash=hash_password(password), display_name=name, settings={})
        db.add(user)
        db.flush()
        adopt_officials(db, user)
        db.commit()
    print(f"已创建：{name}  密码：{password}")


if __name__ == "__main__":
    main()
