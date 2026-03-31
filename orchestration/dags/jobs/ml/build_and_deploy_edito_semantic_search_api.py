from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Param
from airflow.operators.empty import EmptyOperator
from common import macros
from common.callback import on_failure_vm_callback
from common.config import (
    DAG_FOLDER,
    DAG_TAGS,
    ENV_SHORT_NAME,
    DagBaseConfig,
)
from common.operators.gce import (
    DeleteGCEOperator,
    InstallDependenciesOperator,
    SSHGCEOperator,
    StartGCEOperator,
)

# Ariflow params
DEFAULT_ARGS = {
    "start_date": datetime(2022, 11, 30),
    "on_failure_callback": on_failure_vm_callback,
    "retries": 0,
    "retry_delay": timedelta(minutes=2),
}


class GCEConfig(DagBaseConfig):
    instance_name: str = f"build-and-deploy-edito-semantic-search-api-{ENV_SHORT_NAME}"
    instance_type: str = "n1-standard-4"


class DagConfig(DagBaseConfig):
    dag_id: str = "build_and_deploy_edito_semantic_search_api"
    base_dir: str = "data-gcp/jobs/ml_jobs/edito_semantic_search"
    branch: str = "production" if ENV_SHORT_NAME == "prod" else "master"
    python_version: str = "3.11"
    gce_config: GCEConfig = GCEConfig()


DAG_CONFIG = DagConfig()


with DAG(
    DAG_CONFIG.dag_id,
    default_args=DEFAULT_ARGS,
    description="Custom training job",
    schedule_interval=None,
    catchup=False,
    dagrun_timeout=timedelta(minutes=1440),
    user_defined_macros=macros.default,
    template_searchpath=DAG_FOLDER,
    tags=[DAG_TAGS.DS.value, DAG_TAGS.VM.value],
    params={
        "branch": Param(
            default=DAG_CONFIG.branch,
            type="string",
        ),
        "instance_type": Param(
            default=DAG_CONFIG.gce_config.instance_type,
            type="string",
        ),
        "instance_name": Param(
            default=DAG_CONFIG.gce_config.instance_name,
            type="string",
        ),
    },
) as dag:
    start = EmptyOperator(task_id="start", dag=dag)

    gce_instance_start = StartGCEOperator(
        task_id="gce_start_task",
        preemptible=False,
        instance_name="{{ params.instance_name }}",
        instance_type="{{ params.instance_type }}",
        retries=2,
        labels={"job_type": "ml", "dag_name": DAG_CONFIG.dag_id},
    )

    fetch_install_code = InstallDependenciesOperator(
        task_id="fetch_install_code",
        instance_name="{{ params.instance_name }}",
        branch="{{ params.branch }}",
        python_version=DAG_CONFIG.python_version,
        base_dir=DAG_CONFIG.base_dir,
        retries=2,
    )

    build_and_push_docker_image = SSHGCEOperator(
        task_id="build_and_push_docker_image",
        instance_name="{{ params.instance_name }}",
        base_dir=DAG_CONFIG.base_dir,
        command="PYTHONPATH=. uv run python build_and_push_docker_image.py ",
    )

    deploy_model = SSHGCEOperator(
        task_id="deploy_model",
        instance_name="{{ params.instance_name }}",
        base_dir=DAG_CONFIG.base_dir,
        command="PYTHONPATH=. uv run python deploy_model.py ",
    )

    gce_instance_stop = DeleteGCEOperator(
        task_id="gce_stop_task", instance_name="{{ params.instance_name }}"
    )

    (
        start
        >> gce_instance_start
        >> fetch_install_code
        >> build_and_push_docker_image
        >> deploy_model
        >> gce_instance_stop
    )
