# SKILL.md
## When to Use
Tests/DB (post-migration).

## Instructions
1. Use `make postgres-up` Postgres container.
2. Fixtures: `conftest.py` (session, factories).
3. Real hits: Services/API/OOBE.
4. Coverage >80%; audit test vs code.
5. Output: `test_*.py` + Makefile targets.

## Libs
pytest-asyncio, pytest-factoryboy, pytest-cov

## Constraints

- No mocks for DB tests – assert real state/behavior.
- For failing tests, explain "test wrong (update fixture)" vs "code wrong (add field)". Prioritize OOBE flow, then API contract, then tests.
- Do not re-run full test suite after each fix – batch fixes by category (e.g., schema mismatches) to save time.

Files: SKILL.md, template-conftest.py