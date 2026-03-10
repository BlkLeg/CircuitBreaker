hawnji@fedora-laptop:~/Documents/projects/CircuitBreaker$ docker logs circuitbreaker
[init-postgres] Existing Postgres data directory detected at /data/pgdata, skipping init.
[entrypoint] Waiting for Postgres to accept connections...
2026-03-10 13:02:06.413 GMT [25] LOG:  starting PostgreSQL 15.16 (Debian 15.16-0+deb12u1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
2026-03-10 13:02:06.413 GMT [25] LOG:  listening on IPv4 address "127.0.0.1", port 5432
2026-03-10 13:02:06.418 GMT [25] LOG:  listening on Unix socket "/var/run/postgresql/.s.PGSQL.5432"
2026-03-10 13:02:06.425 GMT [28] LOG:  database system was shut down at 2026-03-10 13:01:49 GMT
2026-03-10 13:02:06.426 GMT [29] FATAL:  the database system is starting up
2026-03-10 13:02:06.432 GMT [25] LOG:  database system is ready to accept connections
[migrate] Waiting for Postgres to become ready at 127.0.0.1:5432...
[migrate] Postgres is ready.
[migrate] Ensuring circuitbreaker database exists...
[migrate] Running Alembic migrations from /app/backend...
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
Traceback (most recent call last):
  File "/usr/local/bin/alembic", line 8, in <module>
    sys.exit(main())
             ^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/config.py", line 1047, in main
    CommandLine(prog=prog).main(argv=argv)
  File "/usr/local/lib/python3.12/site-packages/alembic/config.py", line 1037, in main
    self.run_cmd(cfg, options)
  File "/usr/local/lib/python3.12/site-packages/alembic/config.py", line 971, in run_cmd
    fn(
  File "/usr/local/lib/python3.12/site-packages/alembic/command.py", line 483, in upgrade
    script.run_env()
  File "/usr/local/lib/python3.12/site-packages/alembic/script/base.py", line 545, in run_env
    util.load_python_file(self.dir, "env.py")
  File "/usr/local/lib/python3.12/site-packages/alembic/util/pyfiles.py", line 116, in load_python_file
    module = load_module_py(module_id, path)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/util/pyfiles.py", line 136, in load_module_py
    spec.loader.exec_module(module)  # type: ignore
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap_external>", line 999, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/app/backend/migrations/env.py", line 55, in <module>
    run_migrations_online()
  File "/app/backend/migrations/env.py", line 49, in run_migrations_online
    context.run_migrations()
  File "<string>", line 8, in run_migrations
  File "/usr/local/lib/python3.12/site-packages/alembic/runtime/environment.py", line 969, in run_migrations
    self.get_context().run_migrations(**kw)
  File "/usr/local/lib/python3.12/site-packages/alembic/runtime/migration.py", line 614, in run_migrations
    for step in self._migrations_fn(heads, self):
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/command.py", line 472, in upgrade
    return script._upgrade_revs(revision, rev)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/base.py", line 421, in _upgrade_revs
    for script in reversed(list(revs))
                           ^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/revision.py", line 814, in iterate_revisions
    revisions, heads = fn(
                       ^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/revision.py", line 1447, in _collect_upgrade_revisions
    for rev in self._parse_upgrade_target(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/revision.py", line 1234, in _parse_upgrade_target
    return self.get_revisions(target)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/revision.py", line 544, in get_revisions
    resolved_id, branch_label = self._resolve_revision_number(id_)
                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/revision.py", line 768, in _resolve_revision_number
    self._revision_map
  File "/usr/local/lib/python3.12/site-packages/sqlalchemy/util/langhelpers.py", line 1123, in __get__
    obj.__dict__[self.__name__] = result = self.fget(obj)
                                           ^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/revision.py", line 209, in _revision_map
    for revision in self._generator():
                    ^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/base.py", line 155, in _load_revisions
    script = Script._from_path(self, real_path)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/script/base.py", line 1034, in _from_path
    module = util.load_python_file(dir_, filename)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/util/pyfiles.py", line 116, in load_python_file
    module = load_module_py(module_id, path)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/site-packages/alembic/util/pyfiles.py", line 136, in load_module_py
    spec.loader.exec_module(module)  # type: ignore
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap_external>", line 999, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/app/backend/migrations/versions/0001_init.py", line 99, in <module>
    def _copy_server_default(column: sa.Column) -> sa.SchemaItem | None:
                                                   ^^^^^^^^^^^^^
AttributeError: module 'sqlalchemy' has no attribute 'SchemaItem'
[oobe] OOBE marker already present, skipping OOBE hint.
2026-03-10 13:02:10,941 INFO Set uid to user 0 succeeded
2026-03-10 13:02:10,943 INFO supervisord started with pid 7
2026-03-10 13:02:11,946 INFO spawned: 'backend-api' with pid 61
2026-03-10 13:02:11,949 INFO spawned: 'nats' with pid 62
2026-03-10 13:02:11,951 INFO spawned: 'nginx' with pid 63
2026-03-10 13:02:11,954 INFO spawned: 'postgres' with pid 64
2026-03-10 13:02:11,958 INFO spawned: 'worker-00' with pid 65
2026-03-10 13:02:11,961 INFO spawned: 'worker-01' with pid 66
2026-03-10 13:02:11,967 INFO spawned: 'worker-02' with pid 67
2026-03-10 13:02:12,118 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:13.102 GMT [84] ERROR:  relation "webhook_rules" does not exist at character 563
2026-03-10 13:02:13.102 GMT [84] STATEMENT:  SELECT webhook_rules.id AS webhook_rules_id, webhook_rules.name AS webhook_rules_name, webhook_rules.target_url AS webhook_rules_target_url, webhook_rules.secret AS webhook_rules_secret, webhook_rules.topics AS webhook_rules_topics, webhook_rules.events_enabled AS webhook_rules_events_enabled, webhook_rules.headers_json AS webhook_rules_headers_json, webhook_rules.retries AS webhook_rules_retries, webhook_rules.enabled AS webhook_rules_enabled, webhook_rules.created_at AS webhook_rules_created_at, webhook_rules.updated_at AS webhook_rules_updated_at 
	FROM webhook_rules 
	WHERE webhook_rules.enabled = true
2026-03-10 13:02:14,105 INFO spawned: 'postgres' with pid 87
2026-03-10 13:02:14,202 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:15,862 INFO success: nats entered RUNNING state, process has stayed up for > than 3 seconds (startsecs)
2026-03-10 13:02:15,863 INFO success: nginx entered RUNNING state, process has stayed up for > than 3 seconds (startsecs)
2026-03-10 13:02:16,415 INFO spawned: 'postgres' with pid 98
2026-03-10 13:02:16,534 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:17,535 INFO success: backend-api entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
2026-03-10 13:02:17,535 INFO success: worker-00 entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
2026-03-10 13:02:17,536 INFO success: worker-01 entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
2026-03-10 13:02:17,536 INFO success: worker-02 entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
2026-03-10 13:02:19,539 INFO spawned: 'postgres' with pid 101
2026-03-10 13:02:19,660 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:24,222 INFO spawned: 'postgres' with pid 118
2026-03-10 13:02:24,338 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:29,630 INFO spawned: 'postgres' with pid 133
2026-03-10 13:02:29,735 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:36,186 INFO spawned: 'postgres' with pid 150
2026-03-10 13:02:36,279 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:43,741 INFO spawned: 'postgres' with pid 173
2026-03-10 13:02:43,849 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:02:52,403 INFO spawned: 'postgres' with pid 197
2026-03-10 13:02:52,813 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:03:01,923 INFO spawned: 'postgres' with pid 222
2026-03-10 13:03:02,018 WARN exited: postgres (exit status 1; not expected)
2026-03-10 13:03:06.492 GMT [25] LOG:  could not open file "postmaster.pid": No such file or directory
2026-03-10 13:03:06.492 GMT [25] LOG:  performing immediate shutdown because data directory lock file is invalid
2026-03-10 13:03:06.492 GMT [25] LOG:  received immediate shutdown request
2026-03-10 13:03:06.492 GMT [25] LOG:  could not open file "postmaster.pid": No such file or directory
2026-03-10 13:03:06.494 GMT [25] LOG:  database system is shut down
2026-03-10 13:03:12,033 INFO spawned: 'postgres' with pid 250
2026-03-10 13:03:17,081 INFO success: postgres entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)