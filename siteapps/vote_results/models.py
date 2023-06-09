from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords
# Create your models here.

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

from annotations.models import BoundingBox, Category, Species, Activity

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
    
    # Add the history
    history = HistoricalRecords()
    
    def __str__(self):
        return "content_type: {}, object_id: {}, vote_state: {}, close_rule: {}, history: {}".format(\\
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
    # 0 = INVALID - object is invalid
    # 1 = VALID   - object is valid
    vote = models.BooleanField()    
    annotator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True)
    comment = models.TextField()
    
    def _is_staff_expert(annotator):
        # expects an annotator object
        return annotator.objects.get(Q(human__is_staff=True) | Q(human__is_expert=True)) 

    def _get_object(object):        
        # check object type of BoundingBox, Category, Species, Activity        
        if  isinstance(object, BoundingBox):
            return BoundingBox.objects.get(id=object.id)
        elif isinstance(object, Category):
            return Category.objects.get(id=object.id)
        elif isinstance(object, Species):
            return Species.objects.get(id=object.id)
        elif isinstance(object, Activity):
            return Activity.objects.get(id=object.id)
        else:
            # return a object not found exception
            raise Exception("Object not found")

        
    def vote(self, annotator, object, vote, comment):
        try:
            content_object = self._get_object(object)
        except:
            raise
        
        obj, created = VoteResults.get_or_create(content_object=content_object, vote_state=vote)
        # Annotation is staff or expert
        if self._is_staff_expert(annotator):
            obj.vote_state = vote
            obj.close_rule = 'SE'
            obj.save()
        # A new election                        
        elif created:
            obj.vote_state = vote
            obj.save()
        # Uncertain election
        else:
            
            GO FROM HERE.




    
        