import uuid

from django.db import models
from django.db.models import Q
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from images.models import BoundingBox, Category, Species, Activity


class VoteResults(TimeStampedModel):
    CLOSE_CHOICES= (('SE', 'Staff Expert Rule'), ('DV', 'Difference of Votes'))
    
    # Generic Foreign Key to Bounding Box, Category, Species, Activity
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)    
    object_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)    
    content_object = GenericForeignKey()
    
    # Null = UNCERTAIN  -   voting running
    # 0 = INVALID       -   voting closed and object is invalid
    # 1 = VALID         -   voting closed and object is valid
    vote_state = models.BooleanField(null=True)
    close_rule = models.CharField(_("Close Rule"), max_length=2, choices=CLOSE_CHOICES, null=True)
    history = HistoricalRecords()
        
    def get_vote_state(self, new_vote):
        # check rule of difference to close an election or keep open.
        # abs(valid - invalid) + new_vote 
        votes = self.get_votes()        
        total_votes = 0         
        if votes:
            total_votes = votes.filter(vote=1).count() - votes.filter(vote=0).count()
                    
        total_votes += 1 if new_vote else -1            
        if total_votes >= 2: 
            self.vote_state = True
        elif total_votes <= -2: 
            self.vote_state = False
        else:            
            return None # keep voting open
        return True # close voting    
    
    def has_staff_expert_vote(self):
        votes = self.get_votes()
        if votes.filter(annotator__human__is_staff=True).exists() or \
                    votes.filter(annotator__human__is_expert=True).exists():
                        return True
        return False
        
    def is_open(self):                        
        if self.vote_state is not None or self.close_rule is not None:
            raise Exception("Election is closed, no more votes are accepted:\n{}".format(self))
        return True

    def get_votes(self):
        return self.registervote_set.all()
        
    def __str__(self):
        return "{} id: {} \nVote State: {}\nClose Rule: {}".format(self.content_type.model.upper(), 
                                                                    self.object_id, 
                                                                    self.vote_state, 
                                                                    self.close_rule
                                                                    )
                
    class Meta:
        constraints = [
            # Constrain for close_rule only can be not null when vote_state is not null 
            models.CheckConstraint(
                check=Q(vote_state__isnull=True) | Q(close_rule__isnull=False),
                name='close_rule_null_when_vote_state_null'
            )
        ]        
    
    
class RegisterVote(TimeStampedModel):       
    from images.models import Annotator

    # 0 = INVALID - diputed_object is invalid
    # 1 = VALID   - diputed_object is valid
    vote = models.BooleanField()    
    annotator = models.ForeignKey(Annotator, on_delete=models.PROTECT, blank=True, null=True)
    comment = models.TextField()
    vote_results = models.ForeignKey(VoteResults, on_delete=models.CASCADE)    
        
    def pick_vote(self, annotator, diputed_object, vote, comment=''):   
        try:
            self._get_object_class(diputed_object)
        except:
            raise
                
        self.vote = vote
        self.annotator = annotator
        self.comment = comment        
        self.vote_results, created = VoteResults.objects.get_or_create(content_type=self.content_type, object_id=self.object_id)
        
        """
        1. If vote from staff or expert, register vote and close the VoteResults.
        2. ELIF election is new (created), for the current rules, register vote 
           and keep VoteResults open.
        3. ELIF election exists, reconcile vote and close or keep open the VoteResults, 
           based on the rule of difference.
        """
        if self._is_staff_expert(annotator):
            # Double check. This should not be necessary.
            # If staff_expert can chage a closed election, remove this. 
            if not self.vote_results.is_open():
                raise                    
            self.vote_results.vote_state = True if self.vote else False
            self.vote_results.close_rule = 'SE'
        elif not created:
            # Double check. This should not be necessary.
            if not self.vote_results.is_open():
                raise            
            elif self.vote_results.has_staff_expert_vote():
                raise Exception("This election should be closed, since a staff or expert vote exists: {}".format(diputed_object))            
            # Up until now the election is open. Reconciliate and close or keep open.           
            if self.vote_results.get_vote_state(self.vote):
                self.vote_results.close_rule = 'DV'
                
        self.vote_results.save()
        self.save()
    
    def _is_staff_expert(self, annotator):
        return annotator.human.is_staff or annotator.human.is_expert

    def _get_object_class(self, diputed_object):                
        classes = [BoundingBox, Category, Species, Activity]
        for klass in classes:
            if isinstance(diputed_object, klass):                
                try:
                    self.content_type = content_type = ContentType.objects.get_for_model(klass)
                    self.object_id = diputed_object.id
                except klass.DoesNotExist:           
                    raise Exception("Disputed Object not found")
        
    def __str__(self):
        return "Annotator: {}\nVote: {}\nDate: {}".format(self.annotator, self.vote, self.created)


    class Meta:
        constraints = [
            # One annotator cannot vote twice for the same disputed object
            models.UniqueConstraint(fields=['annotator', 'vote_results'], name='unique_annotator_vote_results_constraint')
        ]        
            