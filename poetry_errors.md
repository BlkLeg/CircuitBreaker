shawnji@fedora-laptop:~/Documents/projects/CircuitBreaker$ cd apps/backend && poetry lock && poetry install
Resolving dependencies... (1.3s)

Writing lock file
Installing dependencies from lock file

Package operations: 78 installs, 0 updates, 0 removals

  - Installing pycparser (3.0)
  - Installing cffi (2.0.0)
  - Installing idna (3.11)
  - Installing typing-extensions (4.15.0)
  - Installing annotated-types (0.7.0)
  - Installing anyio (4.12.1)
  - Installing typing-inspection (0.4.2)
  - Installing pydantic-core (2.41.5)
  - Installing argon2-cffi-bindings (25.1.0)
  - Installing annotated-doc (0.0.4)
  - Installing pydantic (2.12.5)
  - Installing bcrypt (5.0.0)
  - Installing dnspython (2.8.0)
  - Installing argon2-cffi (25.1.0)
  - Installing cryptography (46.0.5)
  - Installing starlette (0.52.1)
  - Installing markupsafe (3.0.3)
  - Installing greenlet (3.3.2)
  - Installing pwdlib (0.3.0)
  - Installing email-validator (2.3.0)
  - Installing makefun (1.16.0)
  - Installing fastapi (0.135.1)
  - Installing pyyaml (6.0.3)
  - Installing pyjwt (2.11.0)
  - Installing python-multipart (0.0.22)
  - Installing mdurl (0.1.2)
  - Installing wrapt (2.1.1)
  - Installing deprecated (1.3.1)
  - Installing h11 (0.16.0)
  - Installing markdown-it-py (4.0.0)
  - Installing fastapi-users (15.0.4)
  - Installing click (8.3.1)
  - Installing certifi (2026.2.25)
  - Installing charset-normalizer (3.4.4)
  - Installing packaging (26.0)
  - Installing ptyprocess (0.7.0)
  - Installing urllib3 (2.6.3)
  - Installing sqlalchemy (2.0.47)
  - Installing fastapi-users-db-sqlalchemy (7.0.0)
  - Installing httpcore (1.0.9)
  - Installing requests (2.32.5)
  - Installing tzlocal (5.3.1)
  - Installing limits (5.8.0)
  - Installing mdit-py-plugins (0.5.0)
  - Installing mako (1.3.10)
  - Installing pexpect (4.9.0)
  - Installing pyasn1 (0.6.2)
  - Installing python-dotenv (1.2.2)
  - Installing httptools (0.7.1)
  - Installing watchfiles (1.1.1)
  - Installing webencodings (0.5.1)
  - Installing ifaddr (0.2.0)
  - Installing websockets (16.0)
  - Installing uvloop (0.22.1)
  - Installing aiosmtplib (5.1.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install aiosmtplib.

  - Installing aiosqlite (0.22.1): Failed
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  DBusErrorResponse
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       45│         try:
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       47│             if resp_msg.header.message_type == MessageType.error:
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
    →  48│                 raise DBusErrorResponse(resp_msg)
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       49│             return resp_msg.body
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       50│         except DBusErrorResponse as resp:
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       51│             if resp.name in (
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       52│                 DBUS_UNKNOWN_METHOD,
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
The following error occurred when trying to handle this error:
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  SecretServiceNotAvailableException
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  Remote peer disconnected
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       59│                 data = resp.data
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       60│                 if isinstance(data, tuple):
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       61│                     data = data[0]
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       63│             raise
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       64│ 
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       66│         msg = new_method_call(self, method, signature, body)
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
Cannot install apscheduler.
  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  DBusErrorResponse
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       45│         try:
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       47│             if resp_msg.header.message_type == MessageType.error:
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
    →  48│                 raise DBusErrorResponse(resp_msg)
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       49│             return resp_msg.body
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       50│         except DBusErrorResponse as resp:
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       51│             if resp.name in (
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       52│                 DBUS_UNKNOWN_METHOD,
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
The following error occurred when trying to handle this error:
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  SecretServiceNotAvailableException
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  Remote peer disconnected
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       59│                 data = resp.data
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       60│                 if isinstance(data, tuple):
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       61│                     data = data[0]
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       63│             raise
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       64│ 
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       66│         msg = new_method_call(self, method, signature, body)
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
Cannot install aiosqlite.
  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply

  - Installing alembic (1.18.4): Pending...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
  - Installing alembic (1.18.4): Downloading... 0%
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
  - Installing alembic (1.18.4): Downloading... 100%
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
  - Installing alembic (1.18.4): Installing...
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
  - Installing alembic (1.18.4)
  - Installing apscheduler (3.11.2): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install apscheduler.

  - Installing asyncpg (0.31.0): Failed

  DBusErrorResponse

  [org.freedesktop.DBus.Error.NoReply] ('Remote peer disconnected',)

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:48 in send_and_get_reply
       44│     def send_and_get_reply(self, msg: Message) -> Any:
       45│         try:
       46│             resp_msg: Message = self._connection.send_and_get_reply(msg)
       47│             if resp_msg.header.message_type == MessageType.error:
    →  48│                 raise DBusErrorResponse(resp_msg)
       49│             return resp_msg.body
       50│         except DBusErrorResponse as resp:
       51│             if resp.name in (
       52│                 DBUS_UNKNOWN_METHOD,

The following error occurred when trying to handle this error:


  SecretServiceNotAvailableException

  Remote peer disconnected

  at /usr/lib/python3.14/site-packages/secretstorage/util.py:62 in send_and_get_reply
       58│                                DBUS_NO_REPLY):
       59│                 data = resp.data
       60│                 if isinstance(data, tuple):
       61│                     data = data[0]
    →  62│                 raise SecretServiceNotAvailableException(data) from resp
       63│             raise
       64│ 
       65│     def call(self, method: str, signature: str, *body: Any) -> Any:
       66│         msg = new_method_call(self, method, signature, body)

Cannot install asyncpg.

  - Installing bleach (6.3.0)
  - Installing cachetools (7.0.5)
  - Installing psutil (7.2.2)
  - Installing httpx (0.28.1)
  - Installing psycopg2-binary (2.9.11)
  - Installing pydantic-settings (2.13.1)
  - Installing nats-py (2.14.0)
  - Installing netaddr (1.3.0)
  - Installing pillow (12.1.1)
  - Installing prometheus-client (0.24.1)
  - Installing proxmoxer (2.3.0)
  - Installing pyipmi (0.11.0)
  - Installing pysnmp (7.1.22)
  - Installing pyotp (2.9.0)
  - Installing python-nmap (0.7.1)
  - Installing scapy (2.7.0)
  - Installing slowapi (0.1.9)
  - Installing uvicorn (0.41.0)
  - Installing zeroconf (0.148.0)
