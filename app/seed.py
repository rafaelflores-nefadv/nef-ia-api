from __future__ import annotations

import argparse
from collections.abc import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.operational import DjangoAiRole, DjangoAiUser

DEFAULT_ADMIN_NAME = "Administrador"
DEFAULT_ADMIN_EMAIL = "admin@nef.local"
DEFAULT_ADMIN_PASSWORD = "123456"

ROLE_DEFINITIONS: tuple[tuple[str, int], ...] = (
    ("admin", 100),
    ("gestor", 75),
    ("operador", 50),
    ("visualizador", 25),
)


def _log(message: str) -> None:
    print(f"[seed] {message}")


def _query_roles_by_names(names: Iterable[str]) -> Select[tuple[DjangoAiRole]]:
    return select(DjangoAiRole).where(DjangoAiRole.name.in_(list(names)))


def seed_roles(session: Session, *, force: bool = False) -> dict[str, DjangoAiRole]:
    existing_roles = {
        role.name.lower(): role
        for role in session.execute(
            _query_roles_by_names(name for name, _ in ROLE_DEFINITIONS)
        ).scalars()
    }

    result: dict[str, DjangoAiRole] = {}
    for role_name, access_level in ROLE_DEFINITIONS:
        key = role_name.lower()
        role = existing_roles.get(key)
        if role is None:
            role = DjangoAiRole(
                name=role_name,
                access_level=access_level,
                description=f"Role padrao: {role_name}",
            )
            session.add(role)
            session.flush()
            _log(f"role '{role_name}' criada (access_level={access_level}).")
        else:
            if force and role.access_level != access_level:
                previous = role.access_level
                role.access_level = access_level
                session.flush()
                _log(
                    f"role '{role_name}' atualizada (access_level: {previous} -> {access_level})."
                )
            else:
                _log(
                    f"role '{role_name}' ja existia (access_level={role.access_level})."
                )
        result[key] = role

    return result


def _get_admin_user_by_email(session: Session) -> DjangoAiUser | None:
    stmt = select(DjangoAiUser).where(func.lower(DjangoAiUser.email) == DEFAULT_ADMIN_EMAIL.lower())
    return session.execute(stmt).scalar_one_or_none()


def _get_admin_user_by_name(session: Session) -> DjangoAiUser | None:
    stmt = select(DjangoAiUser).where(func.lower(DjangoAiUser.name) == DEFAULT_ADMIN_NAME.lower())
    return session.execute(stmt).scalar_one_or_none()


def seed_admin_user(
    session: Session,
    *,
    roles: dict[str, DjangoAiRole],
    force: bool = False,
) -> DjangoAiUser:
    admin_role = roles.get("admin")
    if admin_role is None:
        admin_role = session.execute(
            select(DjangoAiRole).where(func.lower(DjangoAiRole.name) == "admin")
        ).scalar_one_or_none()
    if admin_role is None:
        raise RuntimeError("Role 'admin' nao encontrada para seed do usuario administrador.")

    user_by_email = _get_admin_user_by_email(session)
    user_by_name = _get_admin_user_by_name(session)

    user = user_by_email or user_by_name
    if user_by_email and user_by_name and user_by_email.id != user_by_name.id:
        _log(
            "conflito detectado: usuario por email e por nome sao diferentes; "
            "priorizando registro encontrado por email."
        )

    if user is None:
        user = DjangoAiUser(
            name=DEFAULT_ADMIN_NAME,
            email=DEFAULT_ADMIN_EMAIL,
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            role_id=admin_role.id,
            is_active=True,
        )
        session.add(user)
        session.flush()
        _log(f"usuario admin criado ({DEFAULT_ADMIN_EMAIL}).")
        return user

    if force:
        user.name = DEFAULT_ADMIN_NAME
        user.email = DEFAULT_ADMIN_EMAIL
        user.password_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
        user.role_id = admin_role.id
        user.is_active = True
        session.flush()
        _log(f"usuario admin atualizado com --force ({DEFAULT_ADMIN_EMAIL}).")
    else:
        _log(f"usuario admin ja existia ({user.email}).")

    return user


def run_seed(*, force: bool = False) -> None:
    _log("iniciando seed inicial do sistema...")
    with SessionLocal() as session:
        try:
            with session.begin():
                roles = seed_roles(session, force=force)
                seed_admin_user(session, roles=roles, force=force)
        except Exception:
            session.rollback()
            _log("erro durante seed; transacao revertida.")
            raise
    _log("seed concluido com sucesso.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed inicial de roles e usuario administrador.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="atualiza dados padrao mesmo quando os registros ja existem.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    run_seed(force=bool(args.force))


if __name__ == "__main__":
    main()
