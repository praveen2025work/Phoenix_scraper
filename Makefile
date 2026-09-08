# Root Makefile — thin wrappers that cd into backend/ or frontend/.
# See backend/README.md and frontend/README.md for the full command set.
.PHONY: setup demo seed scrape analyze evaluate coverage report api test lint clean \
	ui ui-build ui-types ui-test ui-e2e stack

setup:            ## install backend deps (uv) and frontend deps (npm)
	cd backend && uv sync --all-extras
	cd frontend && npm install

demo:             ## end-to-end offline demo: seed fixtures -> analyze -> report
	cd backend && uv run pheonix demo

seed:             ## seed synthetic fixture spans into the local store
	cd backend && uv run pheonix seed

scrape:           ## one incremental scrape cycle from live Phoenix (needs PHOENIX_* env)
	cd backend && uv run pheonix scrape

analyze:          ## cluster prompts, map skills, persist analysis
	cd backend && uv run pheonix analyze

evaluate:         ## validate stored LLM outputs and user prompts, print the scoreboard
	cd backend && uv run pheonix evaluate

coverage:         ## show what each skill file is asked but doesn't demonstrate
	cd backend && uv run pheonix coverage --write

report:           ## write markdown report + exports to backend/data/exports
	cd backend && uv run pheonix report

api:              ## start the API on :8000 with the job worker + CORS open to the SPA
	cd backend && PHEONIX_CORS_ORIGINS=http://localhost:5173 \
	  uv run uvicorn --factory phoenix_scraper.api:create_app_default --port 8000 --reload

test:             ## backend test suite with coverage
	cd backend && uv run pytest --cov=phoenix_scraper --cov-report=term-missing

lint:             ## backend ruff check
	cd backend && uv run ruff check src tests

clean:            ## remove the local data store and exports
	rm -rf backend/data

ui:               ## frontend dev server on :5173 (talks to :8000 via CORS)
	cd frontend && npm run dev

ui-build:         ## build the SPA to frontend/dist
	cd frontend && npm run build

ui-types:         ## regenerate the typed API client from the live openapi schema
	cd backend && uv run python scripts/gen_openapi.py ../frontend/openapi.json
	cd frontend && npx openapi-typescript openapi.json -o src/api/schema.ts

ui-test:          ## frontend unit tests (vitest)
	cd frontend && npm test

ui-e2e:           ## frontend Playwright smoke (run `npx playwright install chromium` once)
	cd frontend && npm run e2e

stack:            ## reminder: how to run the full stack
	@echo "Two terminals:"
	@echo "  1) make api   # backend + job worker on http://localhost:8000"
	@echo "  2) make ui    # SPA on http://localhost:5173"
	@echo "Production: make ui-build && cd backend && uv run pheonix serve-ui --dist ../frontend/dist"
