install-api:
	uv sync --no-dev
streamlit:
	PYTHONPATH=. streamlit run streamlits/st_visualise_api_response.py
start_app:
	uv run --env-file .env --no-dev hypercorn --bind 0.0.0.0:8085 app.app:app --workers=2
test:
	PYTHONPATH=. pytest tests
build_and_push_docker_image:
	uv run --env-file .env --no-dev build_and_push_docker_image.py
