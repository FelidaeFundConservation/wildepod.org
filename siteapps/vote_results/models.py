from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords
# Create your models here.

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


class VoteResults(TimeStampedModel):
    CLOSE_CHOICES= (('SE', 'Staff Expert Rule'), ('DV', 'Difference of Votes'))
    
    # Generic Foreign Key to Bounding Box, Category, Species, Activity
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
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
        total_votes = votes.filter(vote=1).count() - votes.filter(vote=0).count()
        total_votes += 1 if new_vote else -1            
        if total_votes >= 2: 
            self.vote_state = True
        elif total_votes <= 2: 
            self.vote_state = False
        else:            
            return None # keep voting open
        return True # close voting    
    
    def has_staff_expert_vote(self):
        self.get_votes()
        if self.votes.filter(annotator__human__is_staff=True).exists() or \
                    self.votes.filter(annotator__human__is_expert=True).exists():
                        return True
        return False
        
    def is_open(self):                        
        if self.vote_state is not None or self.close_rule is not None:
            raise Exception("VoteResults is not open for voting for this object: {}".format(self.diputed_object))
        return True

    def get_votes(self):
        self.votes = self.registrevote_set.all()
        
    def __str__(self):
        return "content_type: {}, object_id: {}, vote_state: {}, close_rule: {}, history: {}".format(
                    self.content_type, 
                    self.object_id, 
                    self.vote_state, 
                    self.close_rule, 
                    str(self.history)
                )
                
    class Meta:
        # Constrain for close_rule only can be not null when vote_state is not null 
        constraints = [
            models.CheckConstraint(
                check=Q(vote_state__isnull=True) | Q(close_rule__isnull=False),
                name='close_rule_null_when_vote_state_null'
            )
        ]        
    
    
class RegisterVote(TimeStampedModel):       
    # 0 = INVALID - diputed_object is invalid
    # 1 = VALID   - diputed_object is valid
    vote = models.BooleanField()    
    annotator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True)
    comment = models.TextField()
    vote_results = models.ForeignKey(VoteResults, on_delete=models.CASCADE)    
        
    def annotator_vote(self, annotator, diputed_object, vote, comment=''):        
        try:
            self._get_object_class(diputed_object)
        except:
            raise
                
        self.vote = vote
        self.annotator = annotator
        self.comment = comment        
        obj, created = VoteResults.get_or_create(content_object=self.content_object, vote_state=vote)
        self.vote_results = obj
        
        """
        1. If vote from staff or expert, register vote and close the VoteResults.
        2. ELIF election is new (created), for the current rules, register vote 
           and keep VoteResults open.
        3. ELIF election exists, reconcile vote and close or keep open the VoteResults, 
           based on the rule of difference.
        """
        if self._is_staff_expert(annotator):
            self.vote_results.vote_state = 1 if vote else 0
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
    
    def _is_staff_expert(annotator):
        # expects an annotator object
        return annotator.objects.get(Q(human__is_staff=True) | Q(human__is_expert=True)) 

    def _get_object_class(self, diputed_object):                
        # Import here to avoid circular import
        from annotations.models import BoundingBox, Category, Species, Activity    

        classes = [BoundingBox, Category, Species, Activity]
        for klass in classes:
            if isinstance(diputed_object, klass):                
                self.content_object = klass.objects.get(id=diputed_object.id)
        raise Exception("Disputed Object not found")
        