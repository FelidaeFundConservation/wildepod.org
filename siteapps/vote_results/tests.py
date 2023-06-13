"""
This script makes a simulation of voting. 
It is useful to test the rules of voting, in the models
Cleanup your tables when needed: 
    vote_results_historicalvoteresults
    vote_results_registervote
    vote_results_voteresults
"""

import random

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from images.models import BoundingBox, Category, Species, Activity, Annotator
from .models import VoteResults, RegisterVote



# Get random 10 objects for each model
categories = Category.objects.all().order_by('?')[:10]
species = Species.objects.all().order_by('?')[:10]
bouding_boxes = BoundingBox.objects.all().order_by('?')[:10]
activities = Activity.objects.all().order_by('?')[:10]
objects = [categories, species, bouding_boxes, activities]

# A list of random annotators. The first one is a staff user, 
# so a staff/expert rule should apply in this case. 
# For the other users, the rule of difference should apply.
annotators = ["b638c541-f341-4328-b30a-81392f25b334", 
                "e5a1561b-7eb9-40e8-b54f-1ac14506ac26",
                "32474ca4-5a95-4a05-ae2a-2312aa6736fd",
                "722746e7-6b16-4e30-9818-4b681dd54398",
                "821d9237-cb3d-48f6-8f36-975fda991182",
                "fd7e2627-63d3-43dd-9e39-ecc52bdc1dee",
                "40b1be5e-f326-40ed-9217-703d31da78f6"]


def get_random_element(lst):
    return random.sample(lst, 1)

def check_vote_result(content_type, obj, before=False):
    try:
        vr = VoteResults.objects.get(content_type=content_type, object_id=obj.id)                
        if before: print('Election exists:') 
        print(vr)    
        return vr
    except VoteResults.DoesNotExist:
        print('Election does not exist. It will be created for:')
        print('{}: {}'.format(content_type.model.upper(), obj.id))
        
def print_votes(votes):
    for vote in votes:
        print(vote)


def vote():
    # Vote setup
    human_id = get_random_element(annotators)[0]
    annotator = Annotator.objects.get(human_id=human_id)
    obj = get_random_element(objects)[0][0]
    vote = get_random_element([True, False])[0]
    content_type = ContentType.objects.get_for_model(type(obj))       

    print('\n\n\n\n==================================================')    
    print('ELECTION STATUS BEFORE NEW VOTE')    
    print('-------------------------------')
    vr = check_vote_result(content_type, obj, True)
        

    # Vote
    try:
        rv = RegisterVote()    
        rv.pick_vote(annotator=annotator, diputed_object=obj, vote=vote, comment='')
        print('\n\nNEW VOTE')    
        print('--------')        
        print(rv)
    except Exception as e:
        print('\n\nEXCEPTION ON VOTE')
        print('-----------------')        
        print(e)
    
        print('\nVOTE(S)')    
        print('-------')    
        votes = vr.get_votes()        
        print_votes(votes)        
        print('==================================================')   
        return
    
    # Print Vote Result
    print('\n\nELECTION STATUS AFTER NEW VOTE')    
    print('------------------------------')
    vr = check_vote_result(content_type, obj)
    votes = vr.get_votes()
    
    print('\nVOTE(S)')    
    print('-------')    
    print_votes(votes)
    
    print 
    print('==================================================')
    

idx = 0     
while idx < 100:
    vote()
    idx += 1    

"""
TO RUN TEST:
./manage.py test vote_results --settings=config.settings.local_settings
"""