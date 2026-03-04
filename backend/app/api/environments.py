from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.environments import EnvironmentCreate, EnvironmentUpdate, EnvironmentRead
from app.services.environments_service import (
    list_environments,
    create_environment,
    update_environment,
    delete_environment,
    EnvironmentInUseError,
)

router = APIRouter(tags=["environments"])

_NOT_FOUND = "Environment not found"


@router.get("", response_model=list[EnvironmentRead])
def get_environments(db: Session = Depends(get_db)):
    return list_environments(db)


@router.post("", response_model=EnvironmentRead, status_code=201)
def post_environment(payload: EnvironmentCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        env = create_environment(db, payload.name, payload.color)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Environment name already exists")
    rows = list_environments(db)
    for e in rows:
        if e["id"] == env.id:
            return e
    return {"id": env.id, "name": env.name, "color": env.color, "created_at": env.created_at, "usage_count": 0}


@router.patch("/{environment_id}", response_model=EnvironmentRead)
def patch_environment(environment_id: int, payload: EnvironmentUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        update_environment(db, environment_id, payload.name, payload.color)
    except ValueError:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Environment name already exists")
    rows = list_environments(db)
    for e in rows:
        if e["id"] == environment_id:
            return e
    raise HTTPException(status_code=404, detail=_NOT_FOUND)


@router.delete("/{environment_id}", status_code=204)
def del_environment(environment_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        delete_environment(db, environment_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    except EnvironmentInUseError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": "Environment is in use", "blocking": e.blocking},
        )
