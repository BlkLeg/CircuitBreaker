## Circuit Breaker CI/CD: Test Isolation + Zero-Maintenance Releases

**Goal**: Tests never contaminate `main` or production artifacts. Automated cherry-pick-free branching + release hygiene.

### Strategy: GitHub Actions + Nx/Monorepo Workspaces

**Core Principle**: Tests live in dev-only branches/artifacts. `main` = production-ready code + infra.

***

## 1. Repository Structure (Monorepo w/ Test Isolation)

```
circuitbreaker/
├── apps/                    # Production apps (main branch only)
│   ├── backend/             # FastAPI (no tests/)
│   └── frontend/            # React (no tests/)
├── libs/                    # Shared (no tests/)
├── packages/                # Docker images, installers
├── .github/workflows/       # CI/CD
├── tests/                   # GLOBAL test suite (NEVER in main)
│   ├── e2e/                 # Playwright
│   ├── integration/         # Backend API
│   └── unit/                # Frontend vitest
├── docker/                  # Prod images (COPY apps/ only)
└── Makefile
```

**Key**: `apps/*` = prod code. `tests/` = dev-only, **blocked from merge**.

***

## 2. Branch Protection + Pre-Commit Hooks

**.github/settings/branches/main**:
```
Require PR reviews: 1
Require status checks: ci-test-main, security-scan
Restrict pushes: Admins only
Require linear history: Yes
```

**lint-staged + Husky** (`package.json`):
```json
{
  "lint-staged": {
    "*.{ts,tsx,py}": ["test", "lint"],
    "tests/**": "echo '🚫 Tests blocked from prod paths'"
  },
  "husky": {
    "hooks": {
      "pre-commit": "lint-staged",
      "pre-push": "npm run test:ci"
    }
  }
}
```

**Block Tests from Prod** (`.github/workflows/block-tests.yml`):
```yaml
name: Block Tests in Prod Paths
on: [pull_request]
jobs:
  check-prod:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Block tests/ in apps/
        run: |
          if git diff --name-only origin/main | grep -E "^apps/.*tests/" ; then
            echo "❌ Tests detected in production paths (apps/)"
            exit 1
          fi
```

***

## 3. CI/CD Pipeline (GitHub Actions)

### A. `lint-test.yml` (Every PR/Branch)
```yaml
name: Lint + Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix: [backend, frontend, e2e]
    steps:
      - checkout
      - setup-python
      - pip install -r apps/backend/requirements-dev.txt  # Tests only
      - npm ci --prefix apps/frontend
      - npm run test:ci --prefix apps/frontend
      - pytest tests/integration/ --cov=apps/backend/
      - playwright test tests/e2e/
```

### B. `build-prod.yml` (main + tags only)
```yaml
name: Build Production Artifacts
on:
  push:
    branches: [main]
    tags: [v*.*.*]
jobs:
  build:
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    steps:
      - checkout
      - docker/build-push:
          context: .
          file: docker/Dockerfile.prod  # COPY apps/ EXCLUDES tests/
          push: ${{ github.ref == 'refs/heads/main' }}
          tags: ghcr.io/blkleg/circuitbreaker:${{ github.sha }}, :latest
      - upload-artifact:  # Prod-only binaries
          name: prod-artifacts
          path: |
            apps/backend/dist/
            apps/frontend/dist/
```

### C. `release.yml` (Tags Only)
```yaml
name: Release
on:
  push: { tags: [v*.*.*] }
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - checkout
      - semantic-release  # Auto-changelog from commits
      - gh release create ${{ github.ref_name }}
        files: |
          docker-compose.prod.yml
          packaging/install.sh
```

**Dockerfile.prod** (Tests Excluded):
```dockerfile
FROM python:3.12-alpine AS backend
COPY apps/backend/src /app/src  # NO tests/
RUN pip install -r apps/backend/requirements.txt  # Prod deps only

FROM node:20-alpine AS frontend
COPY apps/frontend /app
RUN npm ci --prod && npm run build

FROM python:3.12-alpine
COPY --from=backend /app /app
COPY --from=frontend /app/dist /app/static
EXPOSE 8080
CMD ["uvicorn", "app.main:app"]
```

***

## 4. Workflow: Cherry-Pick Free Development

```
Developer Workflow:
1. feat/add-rack → develop feature in apps/backend/src/
2. git commit -m "feat: rack simulator"
3. PR to main → Actions: lint-test.yml (runs tests/) → APPROVE → MERGE
4. main → build-prod.yml: prod image (apps/ only)

No cherry-pick needed: tests/ never merges to main
```

**Feature Branches**: Full tests available. `main`: Prod hygiene.

***

## 5. Test Parallelization + Coverage

**.github/workflows/test-parallel.yml**:
```yaml
strategy:
  matrix:
    shard: [1/4, 2/4, 3/4, 4/4]
steps:
  - pytest tests/ --shard=${{ matrix.shard }} --cov-report=xml
  - codecov  # 95%+ coverage threshold
```

**Makefile**:
```makefile
test-unit:  ## Backend unit
	pytest apps/backend/tests/ -v --cov=apps/backend/

test-e2e:   ## End-to-end
	npx playwright test

test-all: test-unit test-e2e  ## All tests
ci: test-all coverage

coverage:
	pytest --cov-report=html  # Enforce 95%+
```

***

## 6. Production Verification

**Image Scanning** (`security.yml`):
```yaml
- name: Scan prod image
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: ghcr.io/blkleg/circuitbreaker:latest
    format: sarif
    output: trivy-results.sarif
- upload-sarif: trivy-results.sarif
```

**Deploy Hooks**:
```
docker pull ghcr.io/blkleg/circuitbreaker:latest  # Tests excluded
docker-compose up -d
curl /api/v1/health  # All green
```

***

## 7. Enforcement Rules

| Rule | Enforcement | Penalty |
|------|-------------|---------|
| `tests/` in `apps/` | Pre-commit + PR block | Reject PR |
| Test deps in prod image | Dockerfile lint + Trivy | Fail build |
| Coverage <95% | Codecov threshold | Block merge |
| Prod image >100MB | Size gates | Fail push |

**Benefits**:
- ✅ `main` = pristine production code
- ✅ Tests run everywhere, never shipped
- ✅ Zero cherry-pick (linear history)
- ✅ Images 30-50% smaller (no test deps)
- ✅ CI <2min (parallel + caching)

**Migration**:
```
1. Restructure: mv tests/ → root/tests/
2. Update imports: apps/backend/tests/ → tests/backend/
3. Enable branch protection
4. `git push origin --delete tests/*` (cleanup)
```

**Estimated**: 4 hours restructure + 2 hours CI tuning. 