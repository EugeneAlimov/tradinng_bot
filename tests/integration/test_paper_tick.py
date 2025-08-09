
from src.presentation.cli.app import run_cli

def test_cli_importable():
    assert callable(run_cli)
