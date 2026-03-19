from __future__ import annotations

import argparse
from collections.abc import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.security import generate_integration_token, hash_token
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.operational import DjangoAiAuditLog, DjangoAiIntegrationToken, DjangoAiRole, DjangoAiUser

DEFAULT_ADMIN_NAME = "Administrador"
DEFAULT_ADMIN_EMAIL = "admin@nef.local"
DEFAULT_ADMIN_PASSWORD = "123456"
DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME = "django-bootstrap"

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


def _get_integration_token_by_name(session: Session, *, token_name: str) -> DjangoAiIntegrationToken | None:
    stmt = select(DjangoAiIntegrationToken).where(func.lower(DjangoAiIntegrationToken.name) == token_name.lower())
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


def seed_bootstrap_integration_token(
    session: Session,
    *,
    created_by_user_id,
    token_name: str = DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME,
) -> str | None:
    normalized_name = str(token_name or "").strip()[:120]
    if not normalized_name:
        normalized_name = DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME

    existing = _get_integration_token_by_name(session, token_name=normalized_name)
    if existing is not None:
        _log(
            f"token bootstrap '{normalized_name}' ja existia; "
            "o valor em texto plano nao sera exibido novamente."
        )
        return None

    raw_token = generate_integration_token()
    token = DjangoAiIntegrationToken(
        name=normalized_name,
        token_hash=hash_token(raw_token),
        is_active=True,
        last_used_at=None,
        created_by_user_id=created_by_user_id,
    )
    session.add(token)
    session.flush()

    session.add(
        DjangoAiAuditLog(
            action_type="integration_token_bootstrap_created",
            entity_type="django_ai_integration_tokens",
            entity_id=str(token.id),
            performed_by_user_id=created_by_user_id,
            changes_json={"name": token.name, "is_active": token.is_active, "bootstrap": True},
            ip_address=None,
        )
    )
    session.flush()
    _log(f"token bootstrap '{normalized_name}' criado.")
    return raw_token


def run_seed(
    *,
    force: bool = False,
    with_bootstrap_token: bool = False,
    bootstrap_token_name: str = DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME,
) -> None:
    _log("iniciando seed inicial do sistema...")
    created_bootstrap_token: str | None = None
    with SessionLocal() as session:
        try:
            with session.begin():
                roles = seed_roles(session, force=force)
                admin_user = seed_admin_user(session, roles=roles, force=force)
                if with_bootstrap_token:
                    created_bootstrap_token = seed_bootstrap_integration_token(
                        session,
                        created_by_user_id=admin_user.id,
                        token_name=bootstrap_token_name,
                    )
        except Exception:
            session.rollback()
            _log("erro durante seed; transacao revertida.")
            raise

    if with_bootstrap_token and created_bootstrap_token:
        _log("copie agora o token bootstrap (exibicao unica):")
        print(created_bootstrap_token)
    _log("seed concluido com sucesso.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed inicial de roles e usuario administrador.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="atualiza dados padrao mesmo quando os registros ja existem.",
    )
    parser.add_argument(
        "--with-bootstrap-token",
        action="store_true",
        help=(
            "cria token de integracao bootstrap padrao "
            f"('{DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME}') se ainda nao existir."
        ),
    )
    parser.add_argument(
        "--bootstrap-token-name",
        default=DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME,
        help=(
            "nome do token bootstrap para uso com --with-bootstrap-token "
            f"(padrao: {DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME})."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    run_seed(
        force=bool(args.force),
        with_bootstrap_token=bool(args.with_bootstrap_token),
        bootstrap_token_name=str(args.bootstrap_token_name or DEFAULT_BOOTSTRAP_INTEGRATION_TOKEN_NAME),
    )


if __name__ == "__main__":
    main()
