import pytest


@pytest.mark.django_db
class TestHelpPage:
    def test_renders_signed_out(self, client):
        response = client.get("/help/")
        assert response.status_code == 200

    def test_covers_all_feature_areas(self, client):
        body = client.get("/help/").content.decode()
        for topic in [
            "join code",
            "fewest completed effort points",
            "Mark done",
            "Request swap",
            "Swap requests for you",
            "Supplies",
            "History",
            "remind",
            "done",
            "confirmation page",
        ]:
            assert topic in body, f"missing help topic: {topic}"

    def test_explains_no_manual_reassignment(self, client):
        body = client.get("/help/").content.decode()
        assert "no manual reassignment" in body

    def test_help_link_on_chores_screen(self, client):
        from .test_services import make_household, make_roommate

        roommate = make_roommate(make_household(), "Ada")
        session = client.session
        session["roommate_id"] = roommate.id
        session.save()

        body = client.get("/chores/").content.decode()
        assert 'href="/help/"' in body

    def test_back_link_to_chores(self, client):
        body = client.get("/help/").content.decode()
        assert 'href="/chores/"' in body
