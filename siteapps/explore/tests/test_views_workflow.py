"""
Tests for explore/views/workflow.py
"""
import json
from unittest.mock import Mock, patch, MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponseServerError
from django.test import RequestFactory
from django.urls import reverse

from explore.views.workflow import WorkflowStateView
from images.models.annotation import Activity, Category, Species

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        email="testuser@example.com",
        password="testpass123",
        name="Test User"
    )


@pytest.fixture
def factory():
    """Create a request factory."""
    return RequestFactory()


@pytest.fixture
def mock_datastore_data():
    """Mock data structure returned from datastore."""
    return {
        "totals": {
            "last_update": "2024-03-20 10:00:00",
            "uploaded_images": 1000,
            "processed_images": 800,
            "not_processed_images": 200,
            "blank_annotation": 150,
            "uncertain_images": 50,
            "species_annotation": 600,
            "animal_activity_annotation": 400,
            "human_behavior_annotation": 200,
        },
        "blank_annotation": {
            "data": json.dumps([[1, 2, 3, 100], [4, 5, 6, 50]]),
        },
        "uncertain_images": {
            "data": json.dumps([[1, 2, 10], [3, 4, 40]]),
        },
        "species_annotation": {
            "data": json.dumps([[1, 2, 300], [3, 4, 300]]),
        },
        "animal_activity": {
            "data": json.dumps([[1, 2, 200], [3, 4, 200]]),
        },
        "human_behavior": {
            "data": json.dumps([[1, 2, 100], [3, 4, 100]]),
        },
    }


class TestGetDatastore:
    """Tests for _get_datastore method."""

    def test_datastore_client_none(self):
        """Test that None client returns HttpResponseServerError."""
        view = WorkflowStateView()
        
        with patch('explore.views.workflow.settings.DATASTORE_CLIENT', None):
            result = view._get_datastore()
            
        assert isinstance(result, HttpResponseServerError)
        assert "Datastore is not available" in str(result.content)

    def test_datastore_exception(self, capsys):
        """Test that exception in datastore access returns error response."""
        view = WorkflowStateView()
        mock_client = Mock()
        mock_client.namespace = None
        mock_client.key.side_effect = Exception("Datastore connection failed")
        
        with patch('explore.views.workflow.settings.DATASTORE_CLIENT', mock_client):
            result = view._get_datastore()
            
        assert isinstance(result, HttpResponseServerError)
        assert "Error in getting data from datastore" in str(result.content)
        
        # Verify exception was printed
        captured = capsys.readouterr()
        assert "Datastore connection failed" in captured.out

    def test_datastore_success(self, mock_datastore_data):
        """Test successful datastore retrieval and data processing."""
        view = WorkflowStateView()
        
        # Create mock client with proper key/get behavior
        mock_client = Mock()
        mock_client.namespace = None
        
        # Mock the key method to return mock keys
        mock_keys = {
            "total": Mock(),
            "blank_annotation": Mock(),
            "uncertain_images": Mock(),
            "species_annotation": Mock(),
            "animal_activity": Mock(),
            "human_behavior": Mock(),
        }
        
        def key_side_effect(key_type, namespace):
            return mock_keys[key_type]
        
        mock_client.key = Mock(side_effect=key_side_effect)
        
        # Mock the get method to return appropriate data
        def get_side_effect(key):
            if key == mock_keys["total"]:
                return mock_datastore_data["totals"]
            elif key == mock_keys["blank_annotation"]:
                return mock_datastore_data["blank_annotation"]
            elif key == mock_keys["uncertain_images"]:
                return mock_datastore_data["uncertain_images"]
            elif key == mock_keys["species_annotation"]:
                return mock_datastore_data["species_annotation"]
            elif key == mock_keys["animal_activity"]:
                return mock_datastore_data["animal_activity"]
            elif key == mock_keys["human_behavior"]:
                return mock_datastore_data["human_behavior"]
            return {}
        
        mock_client.get = Mock(side_effect=get_side_effect)
        
        with patch('explore.views.workflow.settings.DATASTORE_CLIENT', mock_client):
            result = view._get_datastore()
        
        # Verify structure
        assert "totals" in result
        assert "blank_annotation" in result
        assert "uncertain_images" in result
        assert "species_annotation" in result
        assert "animal_activity" in result
        assert "human_behavior" in result
        
        # Verify calculated totals from data arrays
        assert result["totals"]["blank_annotation"] == 150  # sum of last elements: 100 + 50
        assert result["totals"]["uncertain_images"] == 50  # sum of last elements: 10 + 40
        assert result["totals"]["species_annotation"] == 600  # sum: 300 + 300
        assert result["totals"]["animal_activity_annotation"] == 400  # sum: 200 + 200
        assert result["totals"]["human_behavior_annotation"] == 200  # sum: 100 + 100
        
        # Verify data was parsed from JSON
        assert isinstance(result["blank_annotation"]["data"], list)
        assert result["blank_annotation"]["data"] == [[1, 2, 3, 100], [4, 5, 6, 50]]


class TestGetMethod:
    """Tests for get method."""

    def test_get_with_unavailable_datastore(self, factory, user):
        """Test get method when datastore is unavailable."""
        view = WorkflowStateView()
        request = factory.get(reverse("explore:workflow_state"))
        request.user = user
        
        with patch.object(view, '_get_datastore') as mock_get_datastore:
            mock_get_datastore.return_value = HttpResponseServerError("Datastore unavailable")
            response = view.get(request)
        
        assert response.status_code == 503
        assert b"Workflow State Not Available" in response.content
        assert b"not available in local development" in response.content

    def test_get_with_available_datastore(self, factory, user, mock_datastore_data):
        """Test get method when datastore is available."""
        view = WorkflowStateView()
        request = factory.get(reverse("explore:workflow_state"))
        request.user = user
        
        # Mock datastore response
        datastore_response = {
            "totals": mock_datastore_data["totals"],
            "blank_annotation": {"data": [[1, 2, 100]]},
            "uncertain_images": {"data": [[1, 2, 50]]},
            "species_annotation": {"data": [[1, 2, 600]]},
            "animal_activity": {"data": [[1, 2, 400]]},
            "human_behavior": {"data": [[1, 2, 200]]},
        }
        
        with patch.object(view, '_get_datastore') as mock_get_datastore:
            mock_get_datastore.return_value = datastore_response
            with patch('explore.views.workflow.WorkflowStateView.get_context_data') as mock_get_context:
                mock_get_context.return_value = {}
                # Need to mock render to avoid template issues
                with patch('explore.views.workflow.TemplateView.get') as mock_super_get:
                    mock_super_get.return_value = Mock()
                    response = view.get(request)
        
        # Verify datastore was stored in request
        assert hasattr(request, 'datastore')
        assert request.datastore == datastore_response


class TestGetContextData:
    """Tests for get_context_data method."""

    @pytest.fixture
    def mock_request(self, factory, user, mock_datastore_data):
        """Create a mock request with datastore attached."""
        request = factory.get(reverse("explore:workflow_state"))
        request.user = user
        
        # Attach processed datastore data to request
        request.datastore = {
            "totals": {
                "last_update": "2024-03-20 10:00:00",
                "uploaded_images": 1000,
                "processed_images": 800,
                "not_processed_images": 200,
                "blank_annotation": 150,
                "uncertain_images": 50,
                "species_annotation": 600,
                "animal_activity_annotation": 400,
                "human_behavior_annotation": 200,
            },
            "blank_annotation": {"data": [[1, 2, 3, 100], [4, 5, 6, 50]]},
            "uncertain_images": {"data": [[1, 2, 10], [3, 4, 40]]},
            "species_annotation": {"data": [[1, 2, 300], [3, 4, 300]]},
            "animal_activity": {"data": [[1, 2, 200], [3, 4, 200]]},
            "human_behavior": {"data": [[1, 2, 100], [3, 4, 100]]},
        }
        return request

    def test_get_context_data_key_findings(self, mock_request):
        """Test that key findings are added to context."""
        view = WorkflowStateView()
        view.request = mock_request
        
        with patch.object(Category, 'get_categories_group_by') as mock_categories:
            with patch.object(Species, 'get_species_group_by') as mock_species:
                with patch.object(Species, 'get_total_species') as mock_total_species:
                    with patch.object(Activity, 'get_activities_group_by_category') as mock_activities:
                        mock_categories.return_value = []
                        mock_species.return_value = []
                        mock_total_species.return_value = 500
                        mock_activities.return_value = []
                        
                        context = view.get_context_data()
        
        # Verify key findings
        assert context["totals_last_update"] == "2024-03-20 10:00:00"
        assert context["total_images"] == 1000
        assert context["total_images_processed"] == 800
        assert context["total_images_not_processed"] == 200

    def test_get_context_data_category_data(self, mock_request):
        """Test that category data is added to context."""
        view = WorkflowStateView()
        view.request = mock_request
        
        with patch.object(Category, 'get_categories_group_by') as mock_categories:
            with patch.object(Species, 'get_species_group_by') as mock_species:
                with patch.object(Species, 'get_total_species') as mock_total_species:
                    with patch.object(Activity, 'get_activities_group_by_category') as mock_activities:
                        mock_categories.return_value = [{"name": "Animal", "total": 600}]
                        mock_species.return_value = []
                        mock_total_species.return_value = 500
                        mock_activities.return_value = []
                        
                        context = view.get_context_data()
        
        # Verify category data
        assert context["total_blank_annotation"] == 150
        assert context["blank_annotation"]["data"] == [[1, 2, 3, 100], [4, 5, 6, 50]]
        assert context["total_uncertain_images"] == 50
        assert context["uncertain_images"]["data"] == [[1, 2, 10], [3, 4, 40]]

    def test_get_context_data_species_data(self, mock_request):
        """Test that species data is added to context."""
        view = WorkflowStateView()
        view.request = mock_request
        
        with patch.object(Category, 'get_categories_group_by') as mock_categories:
            with patch.object(Species, 'get_species_group_by') as mock_species:
                with patch.object(Species, 'get_total_species') as mock_total_species:
                    with patch.object(Activity, 'get_activities_group_by_category') as mock_activities:
                        mock_categories.return_value = []
                        mock_species.return_value = [{"name": "Tiger", "total": 100}]
                        mock_total_species.return_value = 500
                        mock_activities.return_value = []
                        
                        context = view.get_context_data()
        
        # Verify species data
        assert context["total_species_annotation"] == 600
        assert context["species_annotation"]["data"] == [[1, 2, 300], [3, 4, 300]]
        assert context["species"] == [{"name": "Tiger", "total": 100}]

    def test_get_context_data_animal_activity_data(self, mock_request):
        """Test that animal activity data is added to context."""
        view = WorkflowStateView()
        view.request = mock_request
        
        with patch.object(Category, 'get_categories_group_by') as mock_categories:
            with patch.object(Species, 'get_species_group_by') as mock_species:
                with patch.object(Species, 'get_total_species') as mock_total_species:
                    with patch.object(Activity, 'get_activities_group_by_category') as mock_activities:
                        mock_categories.return_value = []
                        mock_species.return_value = []
                        mock_total_species.return_value = 500
                        # Mock returns different data for animal vs human
                        def activities_side_effect(category):
                            if category == "animal":
                                return [{"name": "Feeding", "total": 150}, {"name": "Walking", "total": 100}]
                            else:
                                return []
                        mock_activities.side_effect = activities_side_effect
                        
                        context = view.get_context_data()
        
        # Verify animal activity data
        assert context["animal_activity"]["data"] == [[1, 2, 200], [3, 4, 200]]
        assert context["total_animal_activity"] == 400
        assert context["animal_activity_observed"] == [{"name": "Feeding", "total": 150}, {"name": "Walking", "total": 100}]

    def test_get_context_data_human_behavior_data(self, mock_request):
        """Test that human behavior data is added to context."""
        view = WorkflowStateView()
        view.request = mock_request
        
        with patch.object(Category, 'get_categories_group_by') as mock_categories:
            with patch.object(Species, 'get_species_group_by') as mock_species:
                with patch.object(Species, 'get_total_species') as mock_total_species:
                    with patch.object(Activity, 'get_activities_group_by_category') as mock_activities:
                        mock_categories.return_value = []
                        mock_species.return_value = []
                        mock_total_species.return_value = 500
                        # Mock returns different data for animal vs human
                        def activities_side_effect(category):
                            if category == "human":
                                return [{"name": "Farming", "total": 80}, {"name": "Collecting", "total": 70}]
                            else:
                                return []
                        mock_activities.side_effect = activities_side_effect
                        
                        context = view.get_context_data()
        
        # Verify human behavior data
        assert context["human_behavior"]["data"] == [[1, 2, 100], [3, 4, 100]]
        assert context["total_human_behavior"] == 200
        assert context["human_behavior_observed"] == [{"name": "Farming", "total": 80}, {"name": "Collecting", "total": 70}]

    def test_get_context_data_pipeline_calculations(self, mock_request):
        """Test pipeline calculation logic in context."""
        view = WorkflowStateView()
        view.request = mock_request
        
        with patch.object(Category, 'get_categories_group_by') as mock_categories:
            with patch.object(Species, 'get_species_group_by') as mock_species:
                with patch.object(Species, 'get_total_species') as mock_total_species:
                    with patch.object(Activity, 'get_activities_group_by_category') as mock_activities:
                        mock_categories.return_value = []
                        mock_species.return_value = []
                        mock_total_species.return_value = 500
                        
                        # Setup activities to return specific totals
                        def activities_side_effect(category):
                            if category == "animal":
                                return [{"total": 150}, {"total": 100}]  # sum = 250
                            else:  # human
                                return [{"total": 80}, {"total": 70}]  # sum = 150
                        mock_activities.side_effect = activities_side_effect
                        
                        context = view.get_context_data()
        
        # Verify category pipeline
        assert context["pipe_category_input"] == 1000
        assert context["pipe_category_first_round"] == 150
        assert context["pipe_category_annotated"] == 850  # 1000 - 150
        
        # Verify species pipeline
        assert context["pipe_species_input"] == 600
        assert context["pipe_species_first_round"] == 100  # 600 - 500
        assert context["pipe_species_annotated"] == 500
        
        # Verify animal activity pipeline
        assert context["pipe_animal_activity_input"] == 650  # 400 + 250
        assert context["pipe_animal_activity_first_round"] == 400
        assert context["pipe_animal_activity_annotated"] == 250
        
        # Verify human behavior pipeline
        assert context["pipe_human_behavior_input"] == 350  # 200 + 150
        assert context["pipe_human_behavior_first_round"] == 200
        assert context["pipe_human_behavior_annotated"] == 150

    def test_get_context_data_includes_all_model_calls(self, mock_request):
        """Test that all model static methods are called."""
        view = WorkflowStateView()
        view.request = mock_request
        
        with patch.object(Category, 'get_categories_group_by') as mock_categories:
            with patch.object(Species, 'get_species_group_by') as mock_species:
                with patch.object(Species, 'get_total_species') as mock_total_species:
                    with patch.object(Activity, 'get_activities_group_by_category') as mock_activities:
                        mock_categories.return_value = []
                        mock_species.return_value = []
                        mock_total_species.return_value = 0
                        mock_activities.return_value = []
                        
                        context = view.get_context_data()
        
        # Verify all methods were called
        mock_categories.assert_called_once()
        mock_species.assert_called_once()
        
        # get_total_species is called twice in the pipeline calculations
        assert mock_total_species.call_count == 2
        
        # Activity method should be called twice (once for animal, once for human)
        assert mock_activities.call_count == 2
        mock_activities.assert_any_call("animal")
        mock_activities.assert_any_call("human")
