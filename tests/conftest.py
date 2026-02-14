"""Shared test fixtures for unit and integration tests."""

import json
import os
import sys

import pytest

# Make testdata importable
sys.path.insert(0, os.path.dirname(__file__))

from testdata import SAMPLE_SUPERVISOR_INFO_RESPONSE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_events_file(tmp_path):
    """Return a path to a temp events JSONL file."""
    return str(tmp_path / "events.jsonl")


@pytest.fixture
def tmp_manifest_file(tmp_path):
    """Return a path to a temp device manifest JSON file."""
    return str(tmp_path / "manifest.json")


@pytest.fixture
def tmp_details_file(tmp_path):
    """Return a path to a temp device details file."""
    return str(tmp_path / "device_details.txt")


@pytest.fixture
def tmp_attached_file(tmp_path):
    """Return a path to a temp attached devices file."""
    return str(tmp_path / "attached_devices.txt")


@pytest.fixture
def mock_subprocess_success(mocker):
    """Mock subprocess.run to always return success (rc=0)."""
    mock = mocker.patch("usbip_lib.usbip.subprocess.run")
    mock.return_value = mocker.Mock(returncode=0, stdout="", stderr="")
    return mock


@pytest.fixture
def mock_supervisor_api(mocker):
    """Mock urllib.request.urlopen to return sample app config."""

    def _make_response(data):
        resp = mocker.Mock()
        resp.read.return_value = json.dumps(data).encode()
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        return resp

    mock_urlopen = mocker.patch("usbip_lib.config.urllib.request.urlopen")
    mock_urlopen.return_value = _make_response(SAMPLE_SUPERVISOR_INFO_RESPONSE)
    return mock_urlopen
