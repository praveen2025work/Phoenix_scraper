.PHONY: setup demo seed scrape analyze report api test lint clean

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

report:           ## write markdown report + exports to data/exports
	uv run pheonix report

api:              ## start the FastAPI service on :8100
	uv run uvicorn --factory phoenix_scraper.api:create_app_default --port 8100 --reload

test:             ## run test suite with coverage
	uv run pytest --cov=phoenix_scraper --cov-report=term-missing

lint:             ## ruff check
	uv run ruff check src tests

clean:            ## remove local data store and exports
	rm -rf data
