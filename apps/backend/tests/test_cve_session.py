from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.db import cve_session


def test_init_cve_db_ignores_existing_table_race(monkeypatch):
    create_mock = Mock(
        side_effect=OperationalError(
            "create table", {}, Exception("table cve_entries already exists")
        )
    )
    has_table_mock = Mock(return_value=True)

    monkeypatch.setattr(cve_session.CVEEntry.__table__, "create", create_mock)
    monkeypatch.setattr(cve_session, "inspect", lambda _engine: Mock(has_table=has_table_mock))

    cve_session.init_cve_db()

    create_mock.assert_called_once_with(bind=cve_session.cve_engine, checkfirst=True)
    has_table_mock.assert_called_once_with(cve_session.CVEEntry.__tablename__)


def test_init_cve_db_re_raises_other_operational_errors(monkeypatch):
    create_mock = Mock(
        side_effect=OperationalError("create table", {}, Exception("disk I/O error"))
    )
    inspect_mock = Mock()

    monkeypatch.setattr(cve_session.CVEEntry.__table__, "create", create_mock)
    monkeypatch.setattr(cve_session, "inspect", lambda _engine: inspect_mock)

    with pytest.raises(OperationalError):
        cve_session.init_cve_db()

    inspect_mock.has_table.assert_not_called()
