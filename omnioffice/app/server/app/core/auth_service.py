"""应用账号体系：注册 / 登录 / 会话（纯标准库实现，不新增依赖）。

为什么自己实现而不引 passlib / python-jose：
- 本应用跑在 fnOS 容器的 slim 镜像里，requirements 越薄越好，打包体积与构建时间
  都是硬约束（瘦身门禁）；
- 需要的只是「口令校验 + 随机会话 token」，pbkdf2_hmac(secrets.token_urlsafe)
  足够，引入第三方库反而增加维护面。

安全约定：
- 口令永不以明文存储，也不写日志；每个账号独立随机盐；
- 校验用 hmac.compare_digest（定长时间比较，避免时序侧信道）；
- 会话 token 由 secrets.token_urlsafe(32) 生成（CSPRNG），服务端落库可吊销；
- **绝不信任客户端自报身份**：一切以网关 X-Trim-* 头为准（避坑指南 §3.1），
  应用会话只在网关身份之上做「二次分流」。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import AuthSession, User

# pbkdf2 迭代次数：OWASP 建议 ≥ 600k（2023），但 NAS 多为 ARM/J1900 级 CPU，
# 经本机实测定在 200k —— 单次登录约 100ms 级，既能抗离线爆破又不拖慢登录。
PBKDF2_ROUNDS = 200_000
SESSION_TOKEN_BYTES = 32
DEFAULT_SESSION_DAYS = 7
REMEMBER_SESSION_DAYS = 30

COOKIE_NAME = "oo_session"

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ 口令


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """返回 (password_hash, salt)。salt 为空时自动生成。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return digest.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return hmac.compare_digest(digest.hex(), stored_hash or "")


def validate_username(username: str) -> str:
    """返回错误说明，通过则返回空串。"""
    name = (username or "").strip()
    if not name:
        return "请输入账号"
    if len(name) < 3 or len(name) > 32:
        return "账号需 3~32 个字符"
    if not _USERNAME_RE.match(name):
        return "账号只能包含字母、数字、下划线、点和短横线，且以字母或数字开头"
    return ""


def validate_password(password: str) -> str:
    pw = password or ""
    if len(pw) < 8 or len(pw) > 128:
        return "密码需 8~128 位"
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        return "密码需同时包含字母和数字"
    return ""


# ------------------------------------------------------------------ 账号 CRUD


def list_users(db: Session, nas_uid: str) -> list[User]:
    """同一 NAS 账号下的全部应用账号。"""
    return list(
        db.scalars(select(User).where(User.nas_uid == nas_uid).order_by(User.id.asc()))
    )


def count_users(db: Session, nas_uid: str | None = None) -> int:
    stmt = select(func.count(User.id))
    if nas_uid:
        stmt = stmt.where(User.nas_uid == nas_uid)
    return int(db.scalar(stmt) or 0)


def get_user_by_username(db: Session, nas_uid: str, username: str) -> User | None:
    name = (username or "").strip()
    return db.scalar(select(User).where(User.nas_uid == nas_uid, User.username == name))


def get_user_by_data_key(db: Session, data_key: str) -> User | None:
    if not data_key:
        return None
    return db.scalar(select(User).where(User.data_key == data_key))


def _new_data_key(db: Session, nas_uid: str) -> str:
    """首个账号沿用 NAS uid（继承历史数据），后续账号用独立随机键。

    这一条是「升级后老数据还在」的关键：升级前所有记录的 owner_uid 就是 NAS uid，
    首个应用账号沿用同一个值，历史周报/模板/导出记录自然可见。
    """
    if count_users(db, nas_uid) == 0:
        return nas_uid
    while True:
        candidate = "u" + secrets.token_hex(8)
        if get_user_by_data_key(db, candidate) is None:
            return candidate


def create_user(
    db: Session,
    nas_uid: str,
    username: str,
    password: str,
    display_name: str = "",
    is_admin: bool | None = None,
) -> User:
    """创建账号。is_admin 为 None 时：该 NAS 账号下的第一个账号自动成为管理员。"""
    pwd_hash, salt = hash_password(password)
    if is_admin is None:
        is_admin = count_users(db, nas_uid) == 0
    row = User(
        username=(username or "").strip(),
        display_name=(display_name or "").strip()[:64],
        password_hash=pwd_hash,
        salt=salt,
        nas_uid=nas_uid,
        data_key=_new_data_key(db, nas_uid),
        is_admin=1 if is_admin else 0,
    )
    db.add(row)
    db.flush()
    return row


def public_user(user: User) -> dict:
    """给前端的账号视图 —— 绝不包含口令散列与盐。"""
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name or user.username,
        "isAdmin": bool(user.is_admin),
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
    }


# ------------------------------------------------------------------ 会话


def issue_session(db: Session, user: User, remember: bool = False, user_agent: str = "") -> tuple[str, datetime]:
    """签发会话，返回 (token, expires_at)。"""
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    days = REMEMBER_SESSION_DAYS if remember else DEFAULT_SESSION_DAYS
    expires = _utcnow() + timedelta(days=days)
    db.add(
        AuthSession(
            token=token,
            user_id=user.id,
            expires_at=expires,
            user_agent=(user_agent or "")[:255],
        )
    )
    db.flush()
    return token, expires


def user_by_token(db: Session, token: str) -> User | None:
    """按 token 取有效会话所属账号；过期/不存在返回 None。"""
    token = (token or "").strip()
    if not token:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.token == token))
    if row is None:
        return None
    if row.expires_at <= _utcnow():
        db.delete(row)
        db.flush()
        return None
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    return user


def revoke_session(db: Session, token: str) -> None:
    row = db.scalar(select(AuthSession).where(AuthSession.token == (token or "").strip()))
    if row is not None:
        db.delete(row)
        db.flush()


def purge_expired_sessions(db: Session) -> int:
    """清理过期会话（登录时顺手做，避免表无限增长）。"""
    expired = list(
        db.scalars(select(AuthSession).where(AuthSession.expires_at <= _utcnow()))
    )
    for row in expired:
        db.delete(row)
    if expired:
        db.flush()
    return len(expired)


# ------------------------------------------------------------------ 登录尝试限流

# 进程内计数即可：这里的告警对象是「同一个人反复猜自己同事的密码」，
# 不需要跨进程精确计数；跨实例场景由 NAS 网关的登录态兜底。
_FAILED: dict[str, list[float]] = {}
_FAILED_WINDOW_S = 300
_FAILED_LIMIT = 8
_FAILED_LOCK_S = 300


def check_login_attempts(key: str) -> int:
    """返回还需等待的秒数（0 = 允许尝试）。"""
    now = _utcnow().timestamp()
    hits = [t for t in _FAILED.get(key, []) if now - t < _FAILED_WINDOW_S]
    _FAILED[key] = hits
    if len(hits) < _FAILED_LIMIT:
        return 0
    waited = now - hits[-_FAILED_LIMIT]
    return max(0, int(_FAILED_LOCK_S - waited))


def note_login_failure(key: str) -> None:
    hits = _FAILED.setdefault(key, [])
    hits.append(_utcnow().timestamp())
    # 只保留窗口内的记录，字典不会无限膨胀
    cutoff = _utcnow().timestamp() - _FAILED_WINDOW_S
    _FAILED[key] = [t for t in hits if t >= cutoff]


def clear_login_failures(key: str) -> None:
    _FAILED.pop(key, None)
