"""
Tests for explore/views/track_volunteer_engagement.py
"""
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
import pytz
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from explore.views.track_volunteer_engagement import (
    TrackVolunteerEngagementView,
    VolunteerEngagementInfo,
    calculate_total_engagement,
    calculate_volunteer_engagement,
)
from images.models import AnnotationCounter, Annotator

User = get_user_model()


@pytest.fixture
def staff_user(db):
    """Create a staff user."""
    return User.objects.create_user(
        email="staff@example.com",
        password="testpass123",
        name="Staff User",
        is_staff=True
    )


@pytest.fixture
def regular_user(db):
    """Create a regular non-staff user."""
    return User.objects.create_user(
        email="user@example.com",
        password="testpass123",
        name="Regular User",
        is_staff=False
    )


@pytest.fixture
def factory():
    """Create a request factory."""
    return RequestFactory()


@pytest.fixture
def annotator(db, regular_user):
    """Create a human annotator."""
    return Annotator.objects.create(
        human=regular_user,
        type="human",
        total_category_annotations=100,
        total_species_annotations=50,
        total_activity_annotations=25
    )


@pytest.fixture
def annotation_counters(db, annotator):
    """Create annotation counters for testing."""
    pacific_tz = pytz.timezone("America/Los_Angeles")
    now = timezone.now().astimezone(pacific_tz)
    
    counters = []
    
    # Create counters for past week (3 days ago)
    three_days_ago = now - timedelta(days=3)
    counters.append(AnnotationCounter.objects.create(
        annotator=annotator,
        annotation_type="category",
        annotation_count=10,
        image_count=8,
        created=three_days_ago
    ))
    counters.append(AnnotationCounter.objects.create(
        annotator=annotator,
        annotation_type="species",
        annotation_count=5,
        image_count=4,
        created=three_days_ago
    ))
    counters.append(AnnotationCounter.objects.create(
        annotator=annotator,
        annotation_type="activity",
        annotation_count=3,
        image_count=2,
        created=three_days_ago
    ))
    
    # Create counters for past month (20 days ago)
    twenty_days_ago = now - timedelta(days=20)
    counters.append(AnnotationCounter.objects.create(
        annotator=annotator,
        annotation_type="category",
        annotation_count=15,
        image_count=12,
        created=twenty_days_ago
    ))
    counters.append(AnnotationCounter.objects.create(
        annotator=annotator,
        annotation_type="species",
        annotation_count=8,
        image_count=6,
        created=twenty_days_ago
    ))
    
    # Create old counter (35 days ago - should be deleted)
    thirty_five_days_ago = now - timedelta(days=35)
    counters.append(AnnotationCounter.objects.create(
        annotator=annotator,
        annotation_type="category",
        annotation_count=20,
        image_count=15,
        created=thirty_five_days_ago
    ))
    
    return counters


class TestVolunteerEngagementInfo:
    """Tests for VolunteerEngagementInfo class."""

    def test_init_creates_object_with_all_fields(self):
        """Test that VolunteerEngagementInfo initializes with all fields."""
        info = VolunteerEngagementInfo(
            id=1,
            name="Test User",
            name_no_spaces="TestUser",
            annotations_past_week=10,
            annotations_past_month=50,
            annotations_all_time=100,
            annotations_past_week_category=5,
            annotations_past_week_species=3,
            annotations_past_week_activity=2,
            annotations_past_month_category=25,
            annotations_past_month_species=15,
            annotations_past_month_activity=10,
            annotations_all_time_category=50,
            annotations_all_time_species=30,
            annotations_all_time_activity=20,
        )
        
        assert info.id == 1
        assert info.name == "Test User"
        assert info.name_no_spaces == "TestUser"
        assert info.annotations_past_week == 10
        assert info.annotations_past_month == 50
        assert info.annotations_all_time == 100
        assert info.annotations_past_week_category == 5
        assert info.annotations_past_week_species == 3
        assert info.annotations_past_week_activity == 2
        assert info.annotations_past_month_category == 25
        assert info.annotations_past_month_species == 15
        assert info.annotations_past_month_activity == 10
        assert info.annotations_all_time_category == 50
        assert info.annotations_all_time_species == 30
        assert info.annotations_all_time_activity == 20


class TestCalculateTotalEngagement:
    """Tests for calculate_total_engagement function."""

    def test_deletes_old_counters(self, db, annotator):
        """Test that counters older than 1 month are deleted."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        
        # Create old counter (35 days ago)
        old_date = now - timedelta(days=35)
        old_counter = AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="category",
            annotation_count=10,
            image_count=5,
            created=old_date
        )
        
        # Create recent counter (3 days ago)
        recent_date = now - timedelta(days=3)
        recent_counter = AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="category",
            annotation_count=5,
            image_count=3,
            created=recent_date
        )
        
        assert AnnotationCounter.objects.count() == 2
        
        context = {}
        with patch('explore.views.track_volunteer_engagement.species_pipeline_query') as mock_species:
            with patch('explore.views.track_volunteer_engagement.activity_pipeline_query') as mock_activity:
                mock_species.return_value.count.return_value = 0
                mock_activity.return_value.count.return_value = 0
                calculate_total_engagement(context)
        
        # Old counter should be deleted
        assert AnnotationCounter.objects.count() == 1
        assert AnnotationCounter.objects.filter(id=recent_counter.id).exists()
        assert not AnnotationCounter.objects.filter(id=old_counter.id).exists()

    def test_calculates_daily_counts_for_30_days(self, db, annotator):
        """Test that daily counts are calculated for 30 days."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        
        # Create counters for today
        today_start = timezone.make_aware(timezone.datetime(now.year, now.month, now.day))
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="category",
            annotation_count=10,
            image_count=8,
            created=today_start
        )
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="species",
            annotation_count=5,
            image_count=4,
            created=today_start
        )
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="activity",
            annotation_count=3,
            image_count=2,
            created=today_start
        )
        
        context = {}
        with patch('explore.views.track_volunteer_engagement.species_pipeline_query') as mock_species:
            with patch('explore.views.track_volunteer_engagement.activity_pipeline_query') as mock_activity:
                mock_species.return_value.count.return_value = 100
                mock_activity.return_value.count.return_value = 50
                calculate_total_engagement(context)
        
        # Check daily counts arrays have 30 elements
        assert len(context["daily_category_counts"]) == 30
        assert len(context["daily_species_counts"]) == 30
        assert len(context["daily_activity_counts"]) == 30
        assert len(context["daily_total_counts"]) == 30
        
        # Today's counts should be non-zero (last element)
        assert context["daily_category_counts"][-1] == 10
        assert context["daily_species_counts"][-1] == 5
        assert context["daily_activity_counts"][-1] == 3
        assert context["daily_total_counts"][-1] == 18  # 10 + 5 + 3

    def test_calculates_daily_averages(self, db, annotator):
        """Test that daily averages are calculated correctly."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        
        # Create counters for multiple days
        for days_ago in [0, 1, 2]:
            day = now - timedelta(days=days_ago)
            day_start = timezone.make_aware(timezone.datetime(day.year, day.month, day.day))
            AnnotationCounter.objects.create(
                annotator=annotator,
                annotation_type="category",
                annotation_count=10,
                image_count=8,
                created=day_start
            )
        
        context = {}
        with patch('explore.views.track_volunteer_engagement.species_pipeline_query') as mock_species:
            with patch('explore.views.track_volunteer_engagement.activity_pipeline_query') as mock_activity:
                mock_species.return_value.count.return_value = 100
                mock_activity.return_value.count.return_value = 50
                calculate_total_engagement(context)
        
        # Averages should be calculated (30 annotations over 30 days = 1.0 avg)
        assert "daily_category_avg" in context
        assert "daily_species_avg" in context
        assert "daily_activity_avg" in context
        assert "daily_total_avg" in context
        assert context["daily_category_avg"] == 1.0  # 30 / 30
        assert isinstance(context["daily_category_avg"], float)

    def test_calculates_pipeline_images(self, db):
        """Test that pipeline image counts are calculated."""
        context = {}
        
        # Mock the pipeline query functions
        mock_species_queryset = Mock()
        mock_species_queryset.count.return_value = 150
        
        mock_animal_queryset = Mock()
        mock_animal_queryset.count.return_value = 75
        
        mock_human_queryset = Mock()
        mock_human_queryset.count.return_value = 50
        
        with patch('explore.views.track_volunteer_engagement.species_pipeline_query') as mock_species:
            with patch('explore.views.track_volunteer_engagement.activity_pipeline_query') as mock_activity:
                mock_species.return_value = mock_species_queryset
                
                def activity_side_effect(images, annotator, activity_category):
                    if activity_category == "animal":
                        return mock_animal_queryset
                    else:
                        return mock_human_queryset
                
                mock_activity.side_effect = activity_side_effect
                calculate_total_engagement(context)
        
        assert context["category_pipeline_images"] == 0  # Always 0 in the code
        assert context["species_pipeline_images"] == 150
        assert context["activity_pipeline_images"] == 125  # 75 + 50

    def test_calculates_images_per_day_rate(self, db, annotator):
        """Test that images per day rate is calculated."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        
        # Create counters with image counts
        for days_ago in range(0, 5):
            day = now - timedelta(days=days_ago)
            day_start = timezone.make_aware(timezone.datetime(day.year, day.month, day.day))
            AnnotationCounter.objects.create(
                annotator=annotator,
                annotation_type="category",
                annotation_count=10,
                image_count=6,  # Total: 5 days * 6 = 30 images
                created=day_start
            )
        
        context = {}
        with patch('explore.views.track_volunteer_engagement.species_pipeline_query') as mock_species:
            with patch('explore.views.track_volunteer_engagement.activity_pipeline_query') as mock_activity:
                mock_species.return_value.count.return_value = 100
                mock_activity.return_value.count.return_value = 50
                calculate_total_engagement(context)
        
        # 30 images / 30 days = 1.0
        assert "daily_category_img_avg" in context
        assert "daily_species_img_avg" in context
        assert "daily_activity_img_avg" in context
        assert context["daily_category_img_avg"] == 1.0

    def test_calculates_estimated_finish_time(self, db):
        """Test that estimated finish time is calculated correctly."""
        context = {}
        
        with patch('explore.views.track_volunteer_engagement.species_pipeline_query') as mock_species:
            with patch('explore.views.track_volunteer_engagement.activity_pipeline_query') as mock_activity:
                mock_species.return_value.count.return_value = 100  # 100 images in pipeline
                mock_activity.return_value.count.return_value = 50   # 50 images in pipeline
                calculate_total_engagement(context)
        
        # Finish time should be calculated (limited to 365 days max)
        assert "category_finish_time" in context
        assert "species_finish_time" in context
        assert "activity_finish_time" in context
        
        # All should be <= 365 days
        assert context["category_finish_time"] <= 365
        assert context["species_finish_time"] <= 365
        assert context["activity_finish_time"] <= 365

    def test_handles_no_counters_gracefully(self, db):
        """Test that function handles absence of counters without errors."""
        context = {}
        
        with patch('explore.views.track_volunteer_engagement.species_pipeline_query') as mock_species:
            with patch('explore.views.track_volunteer_engagement.activity_pipeline_query') as mock_activity:
                mock_species.return_value.count.return_value = 0
                mock_activity.return_value.count.return_value = 0
                calculate_total_engagement(context)
        
        # Should have all required keys even with no data
        assert "daily_category_counts" in context
        assert "daily_total_avg" in context
        assert "category_pipeline_images" in context
        assert len(context["daily_category_counts"]) == 30
        assert context["daily_category_avg"] == 0.0


class TestCalculateVolunteerEngagement:
    """Tests for calculate_volunteer_engagement function."""

    def test_calculates_past_week_annotations(self, db, annotator):
        """Test that past week annotations are calculated correctly."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        
        # Create counters for past week (3 days ago)
        three_days_ago = now - timedelta(days=3)
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="category",
            annotation_count=10,
            image_count=8,
            created=three_days_ago
        )
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="species",
            annotation_count=5,
            image_count=4,
            created=three_days_ago
        )
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="activity",
            annotation_count=3,
            image_count=2,
            created=three_days_ago
        )
        
        context = {}
        volunteers = [annotator]
        calculate_volunteer_engagement(context, volunteers)
        
        assert len(context["volunteer_info"]) == 1
        info = context["volunteer_info"][0]
        assert info.annotations_past_week_category == 10
        assert info.annotations_past_week_species == 5
        assert info.annotations_past_week_activity == 3
        assert info.annotations_past_week == 18  # 10 + 5 + 3

    def test_calculates_past_month_annotations(self, db, annotator):
        """Test that past month annotations are calculated correctly."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        
        # Create counters for past month
        twenty_days_ago = now - timedelta(days=20)
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="category",
            annotation_count=15,
            image_count=12,
            created=twenty_days_ago
        )
        AnnotationCounter.objects.create(
            annotator=annotator,
            annotation_type="species",
            annotation_count=8,
            image_count=6,
            created=twenty_days_ago
        )
        
        context = {}
        volunteers = [annotator]
        calculate_volunteer_engagement(context, volunteers)
        
        assert len(context["volunteer_info"]) == 1
        info = context["volunteer_info"][0]
        assert info.annotations_past_month_category == 15
        assert info.annotations_past_month_species == 8
        assert info.annotations_past_month == 23  # 15 + 8 + 0

    def test_uses_all_time_annotations_from_annotator(self, db, annotator):
        """Test that all time annotations come from annotator fields."""
        context = {}
        volunteers = [annotator]
        calculate_volunteer_engagement(context, volunteers)
        
        assert len(context["volunteer_info"]) == 1
        info = context["volunteer_info"][0]
        assert info.annotations_all_time_category == 100
        assert info.annotations_all_time_species == 50
        assert info.annotations_all_time_activity == 25
        assert info.annotations_all_time == 175  # 100 + 50 + 25

    def test_handles_null_all_time_annotations(self, db, regular_user):
        """Test that null all time annotations are handled as 0."""
        annotator_no_totals = Annotator.objects.create(
            human=regular_user,
            type="human",
            total_category_annotations=None,
            total_species_annotations=None,
            total_activity_annotations=None
        )
        
        context = {}
        volunteers = [annotator_no_totals]
        calculate_volunteer_engagement(context, volunteers)
        
        assert len(context["volunteer_info"]) == 1
        info = context["volunteer_info"][0]
        assert info.annotations_all_time_category == 0
        assert info.annotations_all_time_species == 0
        assert info.annotations_all_time_activity == 0
        assert info.annotations_all_time == 0

    def test_creates_volunteer_info_with_correct_fields(self, db, annotator):
        """Test that VolunteerEngagementInfo is created with correct fields."""
        context = {}
        volunteers = [annotator]
        calculate_volunteer_engagement(context, volunteers)
        
        assert len(context["volunteer_info"]) == 1
        info = context["volunteer_info"][0]
        
        assert info.id == annotator.human.id
        assert info.name == str(annotator)
        assert info.name_no_spaces == str(annotator).replace(" ", "")

    def test_handles_multiple_volunteers(self, db, regular_user):
        """Test that function handles multiple volunteers."""
        # Create second user and annotator
        user2 = User.objects.create_user(
            email="user2@example.com",
            password="testpass123",
            name="User Two",
            is_staff=False
        )
        annotator2 = Annotator.objects.create(
            human=user2,
            type="human",
            total_category_annotations=50,
            total_species_annotations=25,
            total_activity_annotations=10
        )
        
        annotator1 = Annotator.objects.create(
            human=regular_user,
            type="human",
            total_category_annotations=100,
            total_species_annotations=50,
            total_activity_annotations=25
        )
        
        context = {}
        volunteers = [annotator1, annotator2]
        calculate_volunteer_engagement(context, volunteers)
        
        assert len(context["volunteer_info"]) == 2
        
        # Check both volunteers are in the list
        ids = [info.id for info in context["volunteer_info"]]
        assert annotator1.human.id in ids
        assert annotator2.human.id in ids

    def test_handles_no_volunteers(self, db):
        """Test that function handles empty volunteer list."""
        context = {}
        volunteers = []
        calculate_volunteer_engagement(context, volunteers)
        
        # Note: Due to indentation in the original code, volunteer_info is only
        # set inside the for loop, so it won't be in context when list is empty
        # This is a minor bug but we test the actual behavior here
        assert "volunteer_info" not in context


class TestTrackVolunteerEngagementView:
    """Tests for TrackVolunteerEngagementView."""

    def test_requires_login(self, client, db):
        """Test that view requires login."""
        url = reverse("explore:track_volunteer_engagement")
        response = client.get(url)
        
        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_requires_staff_user(self, client, regular_user):
        """Test that view requires staff user."""
        client.force_login(regular_user)
        url = reverse("explore:track_volunteer_engagement")
        response = client.get(url)
        # Non-staff users should be redirected or forbidden
        assert response.status_code in [302, 403]

    def test_staff_user_can_access(self, client, staff_user, db):
        """Test that staff user can access view."""
        client.force_login(staff_user)
        url = reverse("explore:track_volunteer_engagement")
        
        with patch('explore.views.track_volunteer_engagement.calculate_total_engagement'):
            with patch('explore.views.track_volunteer_engagement.calculate_volunteer_engagement'):
                response = client.get(url)
        
        assert response.status_code == 200

    def test_filters_volunteers_by_recent_activity(self, client, staff_user, regular_user, db):
        """Test that only volunteers with recent annotations are included."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        
        # Create annotator with recent activity
        recent_annotator = Annotator.objects.create(
            human=regular_user,
            type="human",
            total_category_annotations=50,
            total_species_annotations=25,
            total_activity_annotations=10
        )
        recent_date = now - timedelta(days=3)
        AnnotationCounter.objects.create(
            annotator=recent_annotator,
            annotation_type="category",
            annotation_count=10,
            image_count=8,
            created=recent_date
        )
        
        # Create annotator with old activity
        user2 = User.objects.create_user(
            email="old@example.com",
            password="testpass123",
            name="Old User",
            is_staff=False
        )
        old_annotator = Annotator.objects.create(
            human=user2,
            type="human",
            total_category_annotations=100,
            total_species_annotations=50,
            total_activity_annotations=25
        )
        old_date = now - timedelta(days=35)
        AnnotationCounter.objects.create(
            annotator=old_annotator,
            annotation_type="category",
            annotation_count=10,
            image_count=8,
            created=old_date
        )
        
        client.force_login(staff_user)
        url = reverse("explore:track_volunteer_engagement")
        
        with patch('explore.views.track_volunteer_engagement.calculate_total_engagement'):
            with patch('explore.views.track_volunteer_engagement.calculate_volunteer_engagement') as mock_calc:
                response = client.get(url)
                
                # Check that calculate_volunteer_engagement was called
                assert mock_calc.called
                # Get the volunteers list passed to the function
                volunteers = mock_calc.call_args[0][1]
                
                # Only recent annotator should be included
                assert len(volunteers) == 1
                assert volunteers[0].id == recent_annotator.id

    def test_only_includes_human_annotators(self, client, staff_user, regular_user, db):
        """Test that only human annotators are included (not bots)."""
        pacific_tz = pytz.timezone("America/Los_Angeles")
        now = timezone.now().astimezone(pacific_tz)
        recent_date = now - timedelta(days=3)
        
        # Create human annotator
        human_annotator = Annotator.objects.create(
            human=regular_user,
            type="human",
            total_category_annotations=50,
        )
        AnnotationCounter.objects.create(
            annotator=human_annotator,
            annotation_type="category",
            annotation_count=10,
            image_count=8,
            created=recent_date
        )
        
        # Create bot annotator
        bot_annotator = Annotator.objects.create(
            human=None,
            type="bot",
            total_category_annotations=1000,
        )
        AnnotationCounter.objects.create(
            annotator=bot_annotator,
            annotation_type="category",
            annotation_count=100,
            image_count=80,
            created=recent_date
        )
        
        client.force_login(staff_user)
        url = reverse("explore:track_volunteer_engagement")
        
        with patch('explore.views.track_volunteer_engagement.calculate_total_engagement'):
            with patch('explore.views.track_volunteer_engagement.calculate_volunteer_engagement') as mock_calc:
                response = client.get(url)
                
                volunteers = mock_calc.call_args[0][1]
                
                # Only human annotator should be included
                assert len(volunteers) == 1
                assert volunteers[0].type == "human"
                assert volunteers[0].id == human_annotator.id

    def test_context_data_includes_calculations(self, client, staff_user, db):
        """Test that context data includes calculation results."""
        client.force_login(staff_user)
        url = reverse("explore:track_volunteer_engagement")
        
        # Mock both calculation functions to set context
        def mock_total_engagement(context):
            context["daily_total_counts"] = [1, 2, 3]
            context["daily_total_avg"] = 2.0
        
        def mock_volunteer_engagement(context, volunteers):
            context["volunteer_info"] = []
        
        with patch('explore.views.track_volunteer_engagement.calculate_total_engagement', side_effect=mock_total_engagement):
            with patch('explore.views.track_volunteer_engagement.calculate_volunteer_engagement', side_effect=mock_volunteer_engagement):
                response = client.get(url)
        
        assert response.status_code == 200
        assert "daily_total_counts" in response.context
        assert "daily_total_avg" in response.context
        assert "volunteer_info" in response.context
