"""
Tests for compute_validity() in processors/annotation.py — the single source
of truth for vote-derived validity on Category, Species, Activity (and the
cascade input for BoundingBox).
"""
import pytest
from images.models import Annotator, BoundingBox, Category, Species, SpeciesName
from siteapps.images.processors.annotation import (
    _is_staff_or_expert,
    _weight,
    compute_validity,
)
from users.models import User


@pytest.fixture
def make_user(db):
    counter = {"i": 0}

    def _make(name="user", staff=False, expert=False):
        counter["i"] += 1
        return User.objects.create_user(
            email=f"{name}{counter['i']}@example.com",
            password="x",
            is_staff=staff,
            is_expert=expert,
        )

    return _make


@pytest.fixture
def make_annotator(make_user):
    def _make(name="user", staff=False, expert=False, is_bot=False, automation_criteria=None):
        if is_bot:
            return Annotator.objects.create(type="bot", automation_criteria=automation_criteria)
        u = make_user(name=name, staff=staff, expert=expert)
        return Annotator.objects.get_or_create(type="human", human=u)[0]

    return _make


@pytest.fixture
def category_with_creator(make_annotator, image):
    """A simple bbox + Category with a normal (non-staff/expert) human creator."""
    creator = make_annotator(name="creator")
    bbox = BoundingBox.objects.create(
        image=image, x=0.1, y=0.1, w=0.5, h=0.5, confidence=0.95, created_by=creator,
    )
    cat = Category.objects.create(
        bounding_box=bbox, name="animal", confidence=0.95, created_by=creator,
    )
    return cat, creator


class TestRoleHelpers:
    def test_is_staff_or_expert_none(self):
        assert _is_staff_or_expert(None) is False

    def test_is_staff_or_expert_normal(self, db, make_annotator):
        assert _is_staff_or_expert(make_annotator()) is False

    def test_is_staff_or_expert_staff(self, db, make_annotator):
        assert _is_staff_or_expert(make_annotator(staff=True)) is True

    def test_is_staff_or_expert_expert(self, db, make_annotator):
        assert _is_staff_or_expert(make_annotator(expert=True)) is True

    def test_is_staff_or_expert_plain_bot(self, db, make_annotator):
        """A bot annotator without an automation criterion has no override authority."""
        assert _is_staff_or_expert(make_annotator(is_bot=True)) is False

    def test_is_staff_or_expert_automation_bot(self, db, make_annotator):
        """A bot annotator carrying an automation criterion is treated like an expert."""
        automation_bot = make_annotator(is_bot=True, automation_criteria="single_human")
        assert _is_staff_or_expert(automation_bot) is True

    def test_weight_normal_is_one(self, db, make_annotator):
        assert _weight(make_annotator()) == 1

    def test_weight_staff_is_five(self, db, make_annotator):
        assert _weight(make_annotator(staff=True)) == 5

    def test_weight_expert_is_five(self, db, make_annotator):
        assert _weight(make_annotator(expert=True)) == 5

    def test_weight_plain_bot_is_one(self, db, make_annotator):
        """A criteria-less bot votes with normal weight."""
        assert _weight(make_annotator(is_bot=True)) == 1

    def test_weight_automation_bot_is_five(self, db, make_annotator):
        """A criteria-bearing automation bot votes with expert-equivalent weight."""
        assert _weight(make_annotator(is_bot=True, automation_criteria="single_human")) == 5

    def test_weight_none_is_one(self):
        assert _weight(None) == 1


class TestComputeValidityDisplayMode:
    """No annotator passed — pure weighted-sum from current M2M state."""

    def test_creator_only_normal_is_uncertain(self, category_with_creator):
        cat, _ = category_with_creator
        result = compute_validity(cat)
        assert result.validity == "UNCERTAIN"
        assert result.score == 1  # creator weight only
        assert result.accepted_count == 0
        assert result.rejected_count == 0
        assert result.staff_override is False

    def test_two_normal_accepts_becomes_valid(self, category_with_creator, make_annotator):
        cat, _ = category_with_creator
        cat.accepted_by.add(make_annotator(name="a"))
        result = compute_validity(cat)
        # creator(1) + 1 accept(1) = 2 -> VALID
        assert result.validity == "VALID"
        assert result.score == 2

    def test_staff_accept_overrides_score(self, category_with_creator, make_annotator):
        cat, _ = category_with_creator
        cat.accepted_by.add(make_annotator(staff=True))
        result = compute_validity(cat)
        # creator(1) + staff(5) = 6 -> VALID
        assert result.validity == "VALID"
        assert result.score == 6
        assert result.staff_accept_count == 1

    def test_staff_reject_pushes_invalid(self, category_with_creator, make_annotator):
        cat, _ = category_with_creator
        cat.rejected_by.add(make_annotator(staff=True))
        result = compute_validity(cat)
        # creator(1) - staff(5) = -4 -> INVALID
        assert result.validity == "INVALID"
        assert result.score == -4
        assert result.staff_reject_count == 1

    def test_expert_treated_same_as_staff(self, category_with_creator, make_annotator):
        cat, _ = category_with_creator
        cat.accepted_by.add(make_annotator(expert=True))
        result = compute_validity(cat)
        assert result.score == 6
        assert result.staff_accept_count == 1


class TestComputeValidityVoteTimeMode:
    """Annotator + accept passed — staff/expert decision wins outright (last vote wins)."""

    def test_staff_accept_at_vote_time_marks_valid_and_override(
        self, category_with_creator, make_annotator
    ):
        cat, _ = category_with_creator
        staff = make_annotator(staff=True)
        result = compute_validity(cat, annotator=staff, accept=True)
        assert result.validity == "VALID"
        assert result.staff_override is True

    def test_staff_reject_at_vote_time_marks_invalid_and_override(
        self, category_with_creator, make_annotator
    ):
        cat, _ = category_with_creator
        # Pre-existing positive votes from many normal users
        for _ in range(10):
            cat.accepted_by.add(make_annotator(name="bulk"))
        staff = make_annotator(staff=True)
        result = compute_validity(cat, annotator=staff, accept=False)
        # Staff reject wins regardless of normal accepts
        assert result.validity == "INVALID"
        assert result.staff_override is True

    def test_normal_voter_at_vote_time_does_not_trigger_override(
        self, category_with_creator, make_annotator
    ):
        cat, _ = category_with_creator
        cat.accepted_by.add(make_annotator(name="a"))  # gets it to VALID
        result = compute_validity(cat, annotator=make_annotator(name="next"), accept=True)
        # Falls through to weighted sum; staff_override stays False
        assert result.validity == "VALID"
        assert result.staff_override is False

    def test_automation_bot_accept_at_vote_time_marks_valid_and_override(
        self, category_with_creator, make_annotator
    ):
        """A single automation-bot accept wins outright, exactly like a staff/expert vote."""
        cat, _ = category_with_creator
        automation_bot = make_annotator(is_bot=True, automation_criteria="single_human")
        result = compute_validity(cat, annotator=automation_bot, accept=True)
        assert result.validity == "VALID"
        assert result.staff_override is True

    def test_plain_bot_accept_at_vote_time_does_not_trigger_override(
        self, category_with_creator, make_annotator
    ):
        """A criteria-less bot has no override authority; it falls through to the weighted sum."""
        cat, _ = category_with_creator  # creator(1) only -> below the +2 threshold
        plain_bot = make_annotator(is_bot=True)
        result = compute_validity(cat, annotator=plain_bot, accept=True)
        # No override; weighted sum of current M2M (creator only) stays UNCERTAIN.
        assert result.validity == "UNCERTAIN"
        assert result.staff_override is False


@pytest.mark.django_db
class TestGetAutomationAnnotator:
    """Provisioning of the dedicated automation bot annotator."""

    def test_creates_distinct_automation_bot_with_criterion(self):
        """The automation annotator is a bot carrying the single_human criterion on a dedicated Bot."""
        from images.processors.annotation import (
            AUTOMATION_BOT_NAME,
            SINGLE_HUMAN_RULE,
            get_automation_annotator,
        )

        annotator = get_automation_annotator()

        assert annotator.type == "bot"
        assert annotator.automation_criteria == SINGLE_HUMAN_RULE
        assert annotator.bot.name == AUTOMATION_BOT_NAME

    def test_is_idempotent(self):
        """Repeated calls return the same annotator and bot (no duplicates)."""
        from images.models import Annotator, Bot
        from images.processors.annotation import AUTOMATION_BOT_NAME, get_automation_annotator

        first = get_automation_annotator()
        second = get_automation_annotator()

        assert first.pk == second.pk
        assert Annotator.objects.filter(automation_criteria="single_human").count() == 1
        assert Bot.objects.filter(name=AUTOMATION_BOT_NAME).count() == 1

    def test_backfills_criterion_on_preexisting_annotator(self):
        """A pre-existing criteria-less annotator on the automation bot is upgraded in place."""
        from images.models import Annotator, Bot
        from images.processors.annotation import (
            AUTOMATION_BOT_NAME,
            AUTOMATION_BOT_VERSION,
            SINGLE_HUMAN_RULE,
            get_automation_annotator,
        )

        bot = Bot.objects.create(name=AUTOMATION_BOT_NAME, version=AUTOMATION_BOT_VERSION)
        stale = Annotator.objects.create(type="bot", bot=bot, automation_criteria=None)

        annotator = get_automation_annotator()

        assert annotator.pk == stale.pk
        annotator.refresh_from_db()
        assert annotator.automation_criteria == SINGLE_HUMAN_RULE

    def test_distinct_from_detection_megadetector_bot(self):
        """The automation bot is a separate Bot from the detection MegaDetector, so detection
        votes keep normal weight while only the automation annotator carries override authority."""
        from images.models import Bot
        from images.processors.annotation import AUTOMATION_BOT_NAME, get_automation_annotator

        get_automation_annotator()

        assert AUTOMATION_BOT_NAME != "MegaDetector"
        assert Bot.objects.filter(name=AUTOMATION_BOT_NAME).exists()
