FROM node:22-bookworm
WORKDIR /opt/panther
COPY infra/package.json infra/package-lock.json ./infra/
RUN cd infra && npm ci --no-audit --no-fund && npx playwright install --with-deps chromium
COPY infra/bin ./infra/bin
COPY infra/lib ./infra/lib
COPY infra/test ./infra/test
COPY infra/tsconfig.json ./infra/tsconfig.json
COPY infra/browser-tests ./infra/browser-tests
COPY infra/lambda ./infra/lambda
COPY src/panther_journal/editorial-plan.json ./src/panther_journal/editorial-plan.json
COPY web/media-explorer ./web/media-explorer
RUN cd infra && npm run build
# Catch missing runtime inputs before an actual character job consumes its retries.
RUN cd infra && npx playwright test browser-tests/viewer.spec.cjs --list
WORKDIR /opt/panther/infra
CMD ["npx", "playwright", "test", "browser-tests/viewer.spec.cjs", "--workers=1", "--reporter=json", "--output=/evidence/browser-results"]
