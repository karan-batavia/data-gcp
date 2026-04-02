##################       Dev       ##################
install:
	uv sync --no-dev
	cp .env.template .env

test:
	PYTHONPATH=. pytest tests

streamlit:
	PYTHONPATH=. streamlit run streamlits/st_visualise_api_response.py

################## 	         API          ##################
start_app:
	uv run --env-file .env --no-dev hypercorn --bind 0.0.0.0:8085 app.app:app --workers=2


##################       Deployment       ##################
build_and_push_docker_image:
	uv run --env-file .env --no-dev build_and_push_docker_image.py

deploy_model:
	uv run --env-file .env --no-dev deploy_model.py
