"""Extended tests for explore views to increase coverage"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from explore.models import Snapshot
from locations.models import Area, County, MacroSite

User = get_user_model()


@pytest.fixture
def macro_site(db):
    """Create a macro site for testing"""
    area = Area.objects.create(name="Test Area")
    county = County.objects.create(name="Test County", area=area)
    return MacroSite.objects.create(name="Test Macro Site", county=county)


@pytest.mark.django_db
class TestSnapshotModelExtended:
    def test_snapshot_pending_status_default(self, user):
        """Test that snapshot has pending status by default"""
        snapshot = Snapshot.objects.create(volunteer=user)

        assert snapshot.status == "pending"

    def test_snapshot_status_choices(self, user):
        """Test different status values"""
        snapshot_pending = Snapshot.objects.create(volunteer=user, status="pending")
        snapshot_done = Snapshot.objects.create(volunteer=user, status="done")
        snapshot_failed = Snapshot.objects.create(volunteer=user, status="failed")

        assert snapshot_pending.status == "pending"
        assert snapshot_done.status == "done"
        assert snapshot_failed.status == "failed"

    def test_snapshot_with_date_range(self, user):
        """Test snapshot with start and end dates"""
        from datetime import date

        snapshot = Snapshot.objects.create(
            volunteer=user,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        assert snapshot.start_date == date(2024, 1, 1)
        assert snapshot.end_date == date(2024, 12, 31)

    def test_snapshot_macrosites_relationship(self, user, macro_site):
        """Test snapshot with macrosites"""
        snapshot = Snapshot.objects.create(volunteer=user)
        snapshot.macrosites.add(macro_site)

        assert macro_site in snapshot.macrosites.all()
        assert snapshot.macrosites.count() == 1

    def test_snapshot_multiple_macrosites(self, user):
        """Test snapshot with multiple macrosites"""
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro1 = MacroSite.objects.create(name="Macro 1", county=county)
        macro2 = MacroSite.objects.create(name="Macro 2", county=county)

        snapshot = Snapshot.objects.create(volunteer=user)
        snapshot.macrosites.add(macro1, macro2)

        assert snapshot.macrosites.count() == 2

    def test_snapshot_ordering(self, user):
        """Test that snapshots are ordered by created"""
        snapshot1 = Snapshot.objects.create(volunteer=user)
        snapshot2 = Snapshot.objects.create(volunteer=user)
        snapshot3 = Snapshot.objects.create(volunteer=user)

        snapshots = list(Snapshot.objects.all())
        assert snapshots[0] == snapshot1
        assert snapshots[1] == snapshot2
        assert snapshots[2] == snapshot3

    def test_snapshot_str_with_user_name(self, user):
        """Test snapshot string representation"""
        user.name = "Test User"
        user.save()

        snapshot = Snapshot.objects.create(volunteer=user)
        str_repr = str(snapshot)

        assert "Test User" in str_repr

    def test_snapshot_blank_dates(self, user):
        """Test snapshot with blank dates"""
        snapshot = Snapshot.objects.create(volunteer=user)

        assert snapshot.start_date is None
        assert snapshot.end_date is None

    def test_snapshot_with_data_file(self, user):
        """Test snapshot with data file"""
        snapshot = Snapshot.objects.create(volunteer=user, data="data/snapshots/test.zip")

        assert snapshot.data.name == "data/snapshots/test.zip"

    def test_snapshot_failed_status(self, user):
        """Test snapshot with failed status"""
        snapshot = Snapshot.objects.create(volunteer=user, status="failed")

        assert snapshot.status == "failed"
        assert snapshot.get_status_display() == "Failed"

    def test_snapshot_done_status(self, user):
        """Test snapshot with done status"""
        snapshot = Snapshot.objects.create(volunteer=user, status="done")

        assert snapshot.status == "done"
        assert snapshot.get_status_display() == "Done"


@pytest.mark.django_db
class TestSnapshotQueryset:
    def test_filter_by_status(self, user):
        """Test filtering snapshots by status"""
        Snapshot.objects.create(volunteer=user, status="pending")
        Snapshot.objects.create(volunteer=user, status="done")
        Snapshot.objects.create(volunteer=user, status="failed")

        pending_snapshots = Snapshot.objects.filter(status="pending")
        done_snapshots = Snapshot.objects.filter(status="done")
        failed_snapshots = Snapshot.objects.filter(status="failed")

        assert pending_snapshots.count() == 1
        assert done_snapshots.count() == 1
        assert failed_snapshots.count() == 1

    def test_filter_by_volunteer(self):
        """Test filtering snapshots by volunteer"""
        user1 = User.objects.create_user(email="user1@test.com")
        user2 = User.objects.create_user(email="user2@test.com")

        Snapshot.objects.create(volunteer=user1)
        Snapshot.objects.create(volunteer=user1)
        Snapshot.objects.create(volunteer=user2)

        user1_snapshots = Snapshot.objects.filter(volunteer=user1)
        user2_snapshots = Snapshot.objects.filter(volunteer=user2)

        assert user1_snapshots.count() == 2
        assert user2_snapshots.count() == 1

    def test_filter_by_date_range(self, user):
        """Test filtering snapshots by date range"""
        from datetime import date

        Snapshot.objects.create(
            volunteer=user,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
        )
        Snapshot.objects.create(
            volunteer=user,
            start_date=date(2024, 7, 1),
            end_date=date(2024, 12, 31),
        )

        first_half = Snapshot.objects.filter(start_date__lte=date(2024, 6, 1))
        second_half = Snapshot.objects.filter(start_date__gte=date(2024, 7, 1))

        assert first_half.count() == 1
        assert second_half.count() == 1
