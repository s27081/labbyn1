"""Smoke tests for Prometheus-related endpoints."""
import pytest


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_prometheus_instances_endpoint(test_client):
    """Smoke test for /prometheus/instances endpoint."""
    response = test_client.get("/prometheus/instances")
    assert response.status_code == 200
    data = response.json()
    assert "instances" in data
    assert isinstance(data["instances"], list)


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_prometheus_hosts_endpoint(test_client):
    """Smoke test for /prometheus/hosts endpoint."""
    response = test_client.get("/prometheus/hosts")
    assert response.status_code == 200
    data = response.json()
    assert "hosts" in data
    assert isinstance(data["hosts"], list)


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint(test_client):
    """Smoke test for /prometheus/metrics endpoint."""
    response = test_client.get("/prometheus/metrics")
    assert response.status_code == 200
    data = response.json()
    excepted_metrics = ["status", "cpu_usage", "memory_usage", "disk_usage"]
    for key in excepted_metrics:
        assert key in data
        assert isinstance(data[key], list)


@pytest.mark.smoke
def test_prometheus_websocket_endpoint(test_client):
    """Smoke test for /ws/metrics WebSocket endpoint."""
    with test_client.websocket_connect("/ws/metrics") as websocket:
        message = websocket.receive_json()
        expected_keys = ["statuses", "metrics"]
        for key in expected_keys:
            assert key in message
            assert isinstance(message[key], list) or isinstance(message[key], dict)
