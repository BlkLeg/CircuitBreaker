from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.core.time import utcnow_iso
from app.db.models import ComputeUnit, Environment, Hardware, Service


def list_environments(db: Session) -> list[dict]:
    rows = (
        db.query(
            Environment,
            func.count(distinct(Hardware.id)).label("hw_count"),
            func.count(distinct(ComputeUnit.id)).label("cu_count"),
            func.count(distinct(Service.id)).label("svc_count"),
        )
        .outerjoin(Hardware, Hardware.environment_id == Environment.id)
        .outerjoin(ComputeUnit, ComputeUnit.environment_id == Environment.id)
        .outerjoin(Service, Service.environment_id == Environment.id)
        .group_by(Environment.id)
        .order_by(Environment.name)
        .all()
    )
    result = []
    for env, hw_count, cu_count, svc_count in rows:
        result.append(
            {
                "id": env.id,
                "name": env.name,
                "color": env.color,
                "created_at": env.created_at,
                "usage_count": hw_count + cu_count + svc_count,
            }
        )
    return result


def create_environment(db: Session, name: str, color: str | None = None) -> Environment:
    existing = db.query(Environment).filter(Environment.name.ilike(name)).first()
    if existing:
        from app.core.errors import ConflictError

        raise ConflictError("Environment already exists")
    env = Environment(
        name=name,
        color=color,
        created_at=utcnow_iso(),
    )
    db.add(env)
    db.commit()
    db.refresh(env)
    return env


def update_environment(
    db: Session, environment_id: int, name: str | None = None, color: str | None = None
) -> Environment:
    env = db.get(Environment, environment_id)
    if env is None:
        raise ValueError(f"Environment {environment_id} not found")
    if name is not None:
        env.name = name
    if color is not None:
        env.color = color
    db.commit()
    db.refresh(env)
    return env


def delete_environment(db: Session, environment_id: int) -> None:
    env = db.get(Environment, environment_id)
    if env is None:
        raise ValueError(f"Environment {environment_id} not found")

    # Clear references so delete is never blocked (environment_id is nullable on all entities)
    db.query(Hardware).filter(Hardware.environment_id == environment_id).update(
        {Hardware.environment_id: None}, synchronize_session="fetch"
    )
    db.query(ComputeUnit).filter(ComputeUnit.environment_id == environment_id).update(
        {ComputeUnit.environment_id: None}, synchronize_session="fetch"
    )
    db.query(Service).filter(Service.environment_id == environment_id).update(
        {Service.environment_id: None}, synchronize_session="fetch"
    )

    db.delete(env)
    db.commit()


def resolve_environment_id(
    db: Session,
    environment_id: int | None,
    environment_name: str | None,
) -> int | None:
    """
    Resolve an environment_id from either a direct FK or an inline name string.
    Follows the same precedence rules as category resolution:
    1. environment_id supplied → use it directly
    2. environment name string → INSERT OR IGNORE, then look up the id
    3. Both → environment_id wins
    4. Neither → None
    """
    if environment_id is not None:
        return environment_id
    if environment_name:
        existing = db.query(Environment).filter(Environment.name.ilike(environment_name)).first()
        if existing:
            return existing.id
        env = Environment(
            name=environment_name,
            created_at=utcnow_iso(),
        )
        db.add(env)
        db.flush()
        return env.id
    return None
