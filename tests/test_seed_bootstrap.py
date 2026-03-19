from uuid import uuid4

from app.core.security import hash_token
from app.models.operational import DjangoAiIntegrationToken
from app.seed import seed_bootstrap_integration_token


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flush_calls += 1


def test_seed_bootstrap_creates_hash_only(monkeypatch) -> None:
    session = FakeSession()
    raw_token = "ia_int_seed_bootstrap_token"

    monkeypatch.setattr("app.seed.generate_integration_token", lambda: raw_token)
    monkeypatch.setattr("app.seed._get_integration_token_by_name", lambda *args, **kwargs: None)

    generated = seed_bootstrap_integration_token(
        session,  # type: ignore[arg-type]
        created_by_user_id=uuid4(),
        token_name="django-bootstrap",
    )

    assert generated == raw_token
    created_token = next(obj for obj in session.added if isinstance(obj, DjangoAiIntegrationToken))
    assert created_token.token_hash == hash_token(raw_token)
    assert created_token.token_hash != raw_token
    assert session.flush_calls >= 2


def test_seed_bootstrap_does_not_regenerate_existing_token(monkeypatch) -> None:
    session = FakeSession()
    existing = DjangoAiIntegrationToken(
        name="django-bootstrap",
        token_hash="already-hashed",
        is_active=True,
        created_by_user_id=uuid4(),
    )

    monkeypatch.setattr("app.seed._get_integration_token_by_name", lambda *args, **kwargs: existing)

    generated = seed_bootstrap_integration_token(
        session,  # type: ignore[arg-type]
        created_by_user_id=uuid4(),
        token_name="django-bootstrap",
    )

    assert generated is None
    assert session.added == []
