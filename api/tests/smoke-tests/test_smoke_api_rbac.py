import uuid


def test_rbac_user_tampering_protection(test_client, rbac_data):
    ac = test_client

    malicious_payload = {"login": "hacked_admin"}

    admin_info = ac.get("/db/users/list_info", headers=rbac_data["admin_b_header"]).json()
    admin_b_id = next(u["id"] for u in admin_info if u["login"] == rbac_data["admin_b_login"])

    res = ac.patch(f"/db/users/{admin_b_id}",
                   json=malicious_payload,
                   headers=rbac_data["user_a_header"])

    assert res.status_code == 403


def test_rbac_unauthorized_team_creation(test_client, rbac_data):
    res = test_client.post("/db/teams/",
                           json={"name": "Malicious Team"},
                           headers=rbac_data["user_a_header"])

    assert res.status_code == 403


def test_rbac_cross_team_shelf_destruction(test_client, service_header_sync, rbac_data):
    ac = test_client
    h_service = service_header_sync

    room_b = ac.post("/db/rooms/", json={
        "name": f"RoomB_{uuid.uuid4().hex[:4]}", "team_id": rbac_data["team_b_id"]
    }, headers=h_service).json()["id"]

    rack_b = ac.post("/db/racks/", json={
        "name": "RackB", "room_id": room_b, "team_id": rbac_data["team_b_id"]
    }, headers=h_service).json()["id"]

    shelf_b = ac.post(f"/db/shelf/{rack_b}",
                      json={"name": "CriticalShelf", "order": 1},
                      headers=h_service).json()["id"]

    res = ac.delete(f"/db/shelf/{shelf_b}", headers=rbac_data["user_a_header"])

    assert res.status_code in [403, 404]


def test_rbac_admin_promotion_isolation(test_client, service_header_sync, rbac_data):
    ac = test_client

    u_a_res = ac.get("/db/users/list_info", headers=service_header_sync).json()
    u_a_id = next(u["id"] for u in u_a_res if u["login"] == rbac_data["user_a_login"])

    res = ac.patch(f"/db/users/{u_a_id}/promote",
                   json={"team_id": rbac_data["team_a_id"], "is_group_admin": True},
                   headers=rbac_data["admin_b_header"])

    assert res.status_code == 403