# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Test cases for explore models (Snapshot).
"""
import pytest
from datetime import date
from explore.models import Snapshot
from locations.models import Area, County, MacroSite


@pytest.mark.django_db
class TestSnapshotModel:
    """Test Snapshot model."""

    def test_snapshot_creation_minimal(self, user):
        """Test creating a Snapshot with minimal required fields."""
        snapshot = Snapshot.objects.create(volunteer=user)
        
        assert snapshot.volunteer == user
        assert snapshot.status == "pending"  # Default status
        assert snapshot.start_date is None
        assert snapshot.end_date is None
        assert not snapshot.data  # FileField is empty
        assert snapshot.pk is not None

    def test_snapshot_creation_with_dates(self, user):
        """Test creating a Snapshot with date filters."""
        start = date(2024, 1, 1)
        end = date(2024, 12, 31)
        
        snapshot = Snapshot.objects.create(
            volunteer=user,
            start_date=start,
            end_date=end
        )
        
        assert snapshot.start_date == start
        assert snapshot.end_date == end
        assert snapshot.status == "pending"

    def test_snapshot_with_macrosites(self, user):
        """Test Snapshot with macrosite filters."""
        # Create location hierarchy
        area = Area.objects.create(name="Test Area")
        county = County.objects.create(name="Test County", area=area)
        macro1 = MacroSite.objects.create(name="Site 1", county=county)
        macro2 = MacroSite.objects.create(name="Site 2", county=county)
        
        snapshot = Snapshot.objects.create(volunteer=user)
        snapshot.macrosites.add(macro1, macro2)
        
        assert snapshot.macrosites.count() == 2
        assert macro1 in snapshot.macrosites.all()
        assert macro2 in snapshot.macrosites.all()

    def test_snapshot_status_choices(self, user):
        """Test different status values."""
        # Pending (default)
        snapshot_pending = Snapshot.objects.create(volunteer=user)
        assert snapshot_pending.status == "pending"
        
        # Done
        snapshot_done = Snapshot.objects.create(volunteer=user, status="done")
        assert snapshot_done.status == "done"
        
        # Failed
        snapshot_failed = Snapshot.objects.create(volunteer=user, status="failed")
        assert snapshot_failed.status == "failed"

    def test_snapshot_str_representation(self, user):
        """Test Snapshot string representation."""
        snapshot = Snapshot.objects.create(volunteer=user)
        expected = f"{user.name}-{snapshot.created}"
        assert str(snapshot) == expected

    def test_snapshot_ordering(self, user):
        """Test Snapshots are ordered by created date."""
        snapshot1 = Snapshot.objects.create(volunteer=user)
        snapshot2 = Snapshot.objects.create(volunteer=user)
        snapshot3 = Snapshot.objects.create(volunteer=user)
        
        snapshots = list(Snapshot.objects.all())
        # Should be ordered by created time (earliest first)
        assert snapshots[0] == snapshot1
        assert snapshots[1] == snapshot2
        assert snapshots[2] == snapshot3

    def test_snapshot_with_data_file(self, user):
        """Test Snapshot can have an attached data file."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        test_file = SimpleUploadedFile("test.csv", b"file_content", content_type="text/csv")
        snapshot = Snapshot.objects.create(volunteer=user, data=test_file)
        
        assert snapshot.data.name.startswith("data/snapshots/")
        assert "test" in snapshot.data.name

    def test_snapshot_volunteer_relationship(self, user, staff_user):
        """Test multiple snapshots can belong to different volunteers."""
        snapshot1 = Snapshot.objects.create(volunteer=user)
        snapshot2 = Snapshot.objects.create(volunteer=staff_user)
        
        assert snapshot1.volunteer == user
        assert snapshot2.volunteer == staff_user
        assert snapshot1.volunteer != snapshot2.volunteer
