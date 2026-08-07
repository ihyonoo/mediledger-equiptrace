"""관리자 핀 편집기(/admin/readers) 통합 테스트."""


class TestListAdminReaders:
    def test_requires_admin_role(self, client, seed_reader, seed_user):
        seed_reader("M101")
        _, headers = seed_user(username="staffer", role="staff")

        response = client.get("/admin/readers", headers=headers)

        assert response.status_code == 403

    def test_returns_reader_with_map_fields(self, client, seed_reader, seed_user):
        seed_reader("M101", location_name="1층 병동 A", is_real_hardware=False)
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.get("/admin/readers", headers=headers)

        assert response.status_code == 200
        body = response.json()
        items = {item["reader_id"]: item for item in body["items"]}
        assert items["M101"]["location_name"] == "1층 병동 A"
        assert items["M101"]["floor"] is None
        assert items["M101"]["map_x"] is None
        assert items["M101"]["map_y"] is None
        assert items["M101"]["is_real_hardware"] is False

    def test_filters_by_floor(self, client, seed_reader, seed_user, db_conn):
        seed_reader("M101")
        seed_reader("M201")
        with db_conn.cursor() as cur:
            cur.execute("UPDATE readers SET floor=1, map_x=10, map_y=20 WHERE reader_id='M101'")
            cur.execute("UPDATE readers SET floor=2, map_x=30, map_y=40 WHERE reader_id='M201'")
        db_conn.commit()
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.get("/admin/readers?floor=1", headers=headers)

        assert response.status_code == 200
        reader_ids = {item["reader_id"] for item in response.json()["items"]}
        assert reader_ids == {"M101"}


class TestUpdateReaderMapPosition:
    def test_requires_admin_role(self, client, seed_reader, seed_user):
        seed_reader("M101")
        _, headers = seed_user(username="staffer", role="staff")

        response = client.put(
            "/admin/readers/M101/map-position",
            json={"floor": 1, "map_x": 12.5, "map_y": 34.0},
            headers=headers,
        )

        assert response.status_code == 403

    def test_sets_floor_and_coordinates(self, client, seed_reader, seed_user, db_conn):
        seed_reader("M101")
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.put(
            "/admin/readers/M101/map-position",
            json={"floor": 1, "map_x": 12.5, "map_y": 34.0},
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()["item"]
        assert body["floor"] == 1
        assert float(body["map_x"]) == 12.5
        assert float(body["map_y"]) == 34.0

        with db_conn.cursor() as cur:
            cur.execute("SELECT floor, map_x, map_y FROM readers WHERE reader_id='M101'")
            row = cur.fetchone()
        assert row == (1, 12.5, 34.0)

    def test_optional_location_name_update(self, client, seed_reader, seed_user, db_conn):
        seed_reader("M101", location_name="기존 이름")
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.put(
            "/admin/readers/M101/map-position",
            json={"floor": 1, "map_x": 12.5, "map_y": 34.0, "location_name": "새 이름"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["item"]["location_name"] == "새 이름"

    def test_rejects_out_of_range_floor(self, client, seed_reader, seed_user):
        seed_reader("M101")
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.put(
            "/admin/readers/M101/map-position",
            json={"floor": 6, "map_x": 10, "map_y": 10},
            headers=headers,
        )

        assert response.status_code == 422

    def test_rejects_out_of_range_coordinate(self, client, seed_reader, seed_user):
        seed_reader("M101")
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.put(
            "/admin/readers/M101/map-position",
            json={"floor": 1, "map_x": 150, "map_y": 10},
            headers=headers,
        )

        assert response.status_code == 422

    def test_unknown_reader_returns_404(self, client, seed_user):
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.put(
            "/admin/readers/NOPE/map-position",
            json={"floor": 1, "map_x": 10, "map_y": 10},
            headers=headers,
        )

        assert response.status_code == 404
