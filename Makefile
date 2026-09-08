.PHONY: setup demo seed scrape analyze evaluate coverage report api test lint clean \
	ui ui-build ui-types ui-test ui-e2e

setup:            ## install deps into .venv via uv
	uv sync --all-extras

demo:             ## end-to-end offline demo: seed fixtures -> analyze -> report
	uv run pheonix demo

seed:             ## seed synthetic fixture spans into the local store
	uv run pheonix seed

scrape:           ## one incremental scrape cycle from live Phoenix (needs PHOENIX_* env)
	uv run pheonix scrape

analyze:          ## cluster prompts, map skills, persist analysis
	uv run pheonix analyze

evaluate:         ## validate stored LLM outputs and user prompts, print the scoreboard
	uv run pheonix evaluate

coverage:         ## show what each skill file is asked but doesn't demonstrate
	uv run pheonix coverage --write

report:           ## write markdown report + exports to data/exports
	uv run pheonix report

api:              ## start the headless API on :8000 (CORS open to the SPA dev server)
	PHEONIX_CORS_ORIGINS=http://localhost:5173 \
	  uv run uvicorn --factory phoenix_scraper.api:create_app_default --port 8000 --reload

test:             ## run test suite with coverage
	uv run pytest --cov=phoenix_scraper --cov-report=term-missing

lint:             ## ruff check
	uv run ruff check src tests

clean:            ## remove local data store and exports
	rm -rf data

ui:               ## frontend dev server on :5173 (talks to :8000 via CORS)
	cd frontend && npm run dev

ui-build:         ## build the SPA to frontend/dist
	cd frontend && npm run build

ui-types:         ## regenerate the typed API client from the app's openapi.json
	uv run python scripts/gen_openapi.py frontend/openapi.json
	cd frontend && npx openapi-typescript openapi.json -o src/api/schema.ts

ui-test:          ## frontend unit tests (vitest)
	cd frontend && npm test

ui-e2e:           ## frontend Playwright smoke (run `npx playwright install chromium` once)
	cd frontend && npm run e2e
