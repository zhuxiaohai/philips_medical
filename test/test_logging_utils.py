import json
import logging
import pathlib
from unittest import mock
from doc_verifier.logging_utils import setup_logging


def test_setup_logging(mocker):
    mock_open = mocker.patch("builtins.open", mock.mock_open(read_data=json.dumps({
        "version": 1,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "DEBUG",
                "formatter": "simple",
                "stream": "ext://sys.stdout"
            }
        },
        "formatters": {
            "simple": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        "root": {
            "level": "DEBUG",
            "handlers": ["console"]
        }
    }).replace("{LOG_PATH}", "/tmp/logs")))

    mocker.patch("pathlib.Path", return_value=pathlib.Path("/fake/path/to/config.json"))
    mocker.patch("logging.config.dictConfig")

    logging_config = setup_logging("/fake/path/to/config.json")

    mock_open.assert_called_once_with(pathlib.Path("/fake/path/to/config.json"))
    logging.config.dictConfig.assert_called_once()
    assert logging_config["version"] == 1
    assert "handlers" in logging_config
    assert "formatters" in logging_config
    assert "root" in logging_config