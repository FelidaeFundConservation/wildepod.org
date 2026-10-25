from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_repo_file(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


def test_predefined_app_engine_configs_include_cost_labels():
    expected_configs = {
        "prod.yaml": {"app_name": "wildepod", "environment": "production"},
        "staging.yaml": {"app_name": "wildepod", "environment": "staging"},
        "bhutan.yaml": {"app_name": "bhutan", "environment": "production"},
    }

    for config_name, labels in expected_configs.items():
        config = _read_repo_file(config_name)

        assert "labels:" in config
        assert f"  app_name: {labels['app_name']}" in config
        assert f"  environment: {labels['environment']}" in config


def test_custom_deployment_config_generation_includes_cost_labels():
    deploy_custom_script = _read_repo_file("deploy_custom.sh")
    template = _read_repo_file("deployment_templates", "TEMPLATE_app_yaml.yaml")

    for content in (deploy_custom_script, template):
        assert "labels:" in content
        assert "  app_name: wildepod" in content
        assert "  environment: development" in content
