import pytest
from django.utils import timezone

from chores.models import Chore, HistoryRecord

from .test_services import make_chore, make_household, make_roommate


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


def record(chore, assignee, points, completed_at, swapped=False):
    return HistoryRecord.objects.create(
        chore=chore,
        assignee=assignee,
        effort_points=points,
        due_at=chore.due_at,
        completed_at=completed_at,
        swapped=swapped,
    )


@pytest.mark.django_db
class TestHistoryScreen:
    def test_lists_records_newest_first_with_details(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ada, name="Water plants")
        older = timezone.now() - timezone.timedelta(days=2)
        newer = timezone.now() - timezone.timedelta(days=1)
        record(chore, ben, 2, older, swapped=True)
        record(chore, ada, 1, newer)

        sign_in(client, ada)
        body = client.get("/history/").content.decode()

        assert body.index("Ada") < body.index("Ben")
        assert "Water plants" in body
        assert "swapped" in body
        assert "1 pt" in body
        assert "2 pts" in body

    def test_only_household_records_visible(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        other = make_household("OTHER1")
        foreign_chore = make_chore(other, make_roommate(other, "Zoe"), name="Foreign")
        record(foreign_chore, foreign_chore.assignee, 3, timezone.now())

        sign_in(client, ada)
        body = client.get("/history/").content.decode()

        assert "Foreign" not in body

    def test_pagination_caps_at_fifty_per_page(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Dishes")
        for i in range(55):
            record(chore, ada, 1, timezone.now() - timezone.timedelta(minutes=i))

        sign_in(client, ada)
        page1 = client.get("/history/").content.decode()
        page2 = client.get("/history/?page=2").content.decode()

        assert "Page 1 of 2" in page1
        assert "Page 2 of 2" in page2
        assert page1.count("Dishes") == 50
        assert page2.count("Dishes") == 5

    def test_empty_history_shows_message(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)
        body = client.get("/history/").content.decode()
        assert "No completed chores yet" in body

    def test_signed_out_redirected(self, client):
        response = client.get("/history/")
        assert response.status_code == 302
        assert response.url == "/"

    def test_chores_screen_links_to_history(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)
        body = client.get("/chores/").content.decode()
        assert 'href="/history/"' in body
