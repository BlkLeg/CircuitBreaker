import ast

def fix_auth_test():
    with open("tests/integration/test_auth.py", "r") as f:
        content = f.read()
    
    # Simple search and replace for the missing unauth
    # test_settings_put_requires_auth
    content = content.replace(
        '# Now unauthenticated PUT should be blocked\n    resp = client.put("/api/v1/settings", json={"theme": "light"})',
        '# Now unauthenticated PUT should be blocked\n    client.cookies.clear()\n    resp = client.put("/api/v1/settings", json={"theme": "light"})'
    )
    # test_settings_reset_requires_auth
    content = content.replace(
        '# Unauthenticated reset should be blocked\n    resp = client.post("/api/v1/settings/reset")',
        '# Unauthenticated reset should be blocked\n    client.cookies.clear()\n    resp = client.post("/api/v1/settings/reset")'
    )
    # test_logs_delete_requires_auth
    content = content.replace(
        'headers=_auth_header(token),\n    )\n    resp = client.delete("/api/v1/logs")',
        'headers=_auth_header(token),\n    )\n    client.cookies.clear()\n    resp = client.delete("/api/v1/logs")'
    )
    # test_get_me_no_token
    content = content.replace(
        'headers=_auth_header(token),\n        )\n        resp = client.get("/api/v1/auth/me")',
        'headers=_auth_header(token),\n        )\n        client.cookies.clear()\n        resp = client.get("/api/v1/auth/me")'
    )
    # test_delete_me_unauthenticated
    content = content.replace(
        'headers=_auth_header(token),\n        )\n        resp = client.delete("/api/v1/auth/me")',
        'headers=_auth_header(token),\n        )\n        client.cookies.clear()\n        resp = client.delete("/api/v1/auth/me")'
    )

    with open("tests/integration/test_auth.py", "w") as f:
        f.write(content)

fix_auth_test()
