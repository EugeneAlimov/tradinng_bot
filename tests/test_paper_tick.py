from src.presentation.cli.app import main


def test_cli_importable():
    assert callable(main())
