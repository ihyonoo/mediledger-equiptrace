"""GET /rtls/live의 is_real_hardware role 기반 노출 제어 통합 테스트.

직원(staff)에게는 is_real_hardware 필드 자체가 응답에 없어야 하고(값이 null이 아니라
키 자체가 부재), 관리자(admin)에게는 리더·태그 양쪽에 실제 값이 노출돼야 한다.
"""


class TestRtlsLiveProvenanceVisibility:
    def test_staff_response_omits_is_real_hardware(self, client, seed_reader, seed_tag, seed_user):
        seed_reader("M999", is_real_hardware=False)
        seed_tag("EQ-SIM-0001", is_real_hardware=False)
        _, headers = seed_user(username="staffer", role="staff")

        response = client.get("/rtls/live", headers=headers)

        assert response.status_code == 200
        body = response.json()
        reader_item = next(r for r in body["readers"] if r["reader_id"] == "M999")
        tag_item = next(i for i in body["items"] if i["tag_id"] == "EQ-SIM-0001")
        assert "is_real_hardware" not in reader_item
        assert "is_real_hardware" not in tag_item

    def test_admin_response_includes_is_real_hardware(self, client, seed_reader, seed_tag, seed_user):
        seed_reader("M999", is_real_hardware=False)
        seed_tag("EQ-SIM-0001", is_real_hardware=False)
        seed_tag("EQ-REAL-0001", is_real_hardware=True)
        _, headers = seed_user(username="admin1", role="admin", position=None)

        response = client.get("/rtls/live", headers=headers)

        assert response.status_code == 200
        body = response.json()
        reader_item = next(r for r in body["readers"] if r["reader_id"] == "M999")
        sim_tag = next(i for i in body["items"] if i["tag_id"] == "EQ-SIM-0001")
        real_tag = next(i for i in body["items"] if i["tag_id"] == "EQ-REAL-0001")
        assert reader_item["is_real_hardware"] is False
        assert sim_tag["is_real_hardware"] is False
        assert real_tag["is_real_hardware"] is True

    def test_readers_include_floor_and_map_coordinates_for_staff(self, client, seed_reader, seed_user, db_conn):
        seed_reader("M999")
        with db_conn.cursor() as cur:
            cur.execute("UPDATE readers SET floor=3, map_x=11.5, map_y=22.5 WHERE reader_id='M999'")
        db_conn.commit()
        _, headers = seed_user(username="staffer", role="staff")

        response = client.get("/rtls/live", headers=headers)

        assert response.status_code == 200
        reader_item = next(r for r in response.json()["readers"] if r["reader_id"] == "M999")
        assert reader_item["floor"] == 3
        assert float(reader_item["map_x"]) == 11.5
        assert float(reader_item["map_y"]) == 22.5
