"""Offline HTTP-contract tests for the local Narwal dashboard."""

import asyncio

from narwal_dashboard import RobotSettings, _map_with_local_room_names, create_app


def test_local_room_names_decorate_only_matching_room_ids():
    original = {
        "map_id": 1,
        "rooms": [
            {"id": 2, "name": None, "type": None},
            {"id": 3, "name": None, "type": 6},
            {"id": 7, "name": "Robot-provided name", "type": 10},
        ],
    }

    decorated = _map_with_local_room_names(original, {2: "Den", 3: "Guest bathroom"})

    assert [room["name"] for room in decorated["rooms"]] == [
        "Den",
        "Guest bathroom",
        "Robot-provided name",
    ]
    assert original["rooms"][0]["name"] is None


def test_dashboard_serves_locally_and_requires_explicit_action_confirmation():
    app = create_app(RobotSettings("192.0.2.50"))
    client = app.test_client()

    page = client.get("/")
    rejected = client.post("/api/actions/home", json={})

    assert page.status_code == 200
    assert "שליטה מקומית" in page.get_data(as_text=True)
    assert page.headers["Cache-Control"] == "no-store"
    assert rejected.status_code == 400
    assert "אישור מפורש" in rejected.get_json()["error"]


def test_dashboard_serializes_runner_results_without_a_real_robot():
    calls = []

    async def fake_runner(settings, operation, payload):
        calls.append((settings.host, operation, payload))
        await asyncio.sleep(0)
        return {"operation": operation, "accepted": True}

    app = create_app(RobotSettings("192.0.2.50"), runner=fake_runner)
    client = app.test_client()

    status = client.get("/api/status")
    action = client.post("/api/actions/locate", json={"confirm": True})

    assert status.status_code == 200
    assert status.get_json()["operation"] == "status"
    assert action.status_code == 200
    assert action.get_json()["operation"] == "locate"
    assert calls == [
        ("192.0.2.50", "status", {}),
        ("192.0.2.50", "locate", {"confirm": True}),
    ]
