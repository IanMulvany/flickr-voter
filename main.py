#!/usr/bin/env python
import logging
from datetime import datetime, date, time
from django.utils import simplejson
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template
from google.appengine.api import urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.api.labs.taskqueue import Queue
from google.appengine.api import mail
from xml.dom import minidom
import os

from config import apikey
from config import GROUPID
from config import FETCHLIMIT
from config import PAGINGLIMIT

FLICKRKEY = apikey

# data classes

class TaskMonitor(db.Model):
    queue = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add=True)

class MailRecipients(db.Model):
    email = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)

class Photo(db.Model):
    uid = db.StringProperty(required=True)
    title = db.StringProperty()
    owner_id = db.StringProperty()
    owner_name = db.StringProperty()     
    photopage_url = db.StringProperty()
    photoimage_url = db.StringProperty()
    photothumb_url = db.StringProperty()
    last_modified = db.StringProperty()

class PhotoActivity(db.Model):
    activity_id = db.StringProperty(required=True)
    photo_id = db.StringProperty(required=True)
    author = db.StringProperty()
    activity_type = db.StringProperty()
    activity_content = db.StringProperty()
    vote_sum = db.IntegerProperty(default=0)
    vote_count = db.IntegerProperty(default=0)
    created = db.DateTimeProperty(auto_now_add=True)
    
class UniqueContributors(db.Model):
    # in creating this we can later add more user info, such as user name,
    # taken from flickr via a call to that api
    author = db.StringProperty(required=True)
    last_activity_date = db.DateTimeProperty()
    last_activity_id = db.StringProperty()
    vote_sum = value = db.IntegerProperty(default=0)
    vote_count = value = db.IntegerProperty(default=0)
    created = db.DateTimeProperty(auto_now_add=True)
    
class Vote(db.Model):
    "we don't need a uid, as every vote action is stored, if a vote happens twice due to concurrency issues, ow well, it's not very important"
    recipient = db.StringProperty()
    voter = db.StringProperty()
    value = db.IntegerProperty(required=True, default=0) # I'd like to set this to a default value of 0, but I don't know how to
    activity_id = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add=True)


    
# getters and setters for the data classes 
    

def getUniqueContributor(author):
    try:
        query = db.Query(UniqueContributors)
        query.filter('author =', author)
        c  = query.fetch(limit=1)
        return c[0] 
    except:
        return None 

def create_contributor_record(target):
    def wrapper(*args, **kwargs):
        activity_id = args[0]
        author = args[2]
        now = datetime.now()
        uc = getUniqueContributor(author)
        if uc:
            uc.last_activity_date = now
            uc.last_activity_id = activity_id
            uc.put()
            return target(*args, **kwargs)
        else:
            uc = UniqueContributors(author=author)
            uc.last_activity_date = now
            uc.last_activity_id = activity_id
            uc.put()
            return target(*args, **kwargs)
    return wrapper
    
# use a decorator to create contributor ids in a seperate datastore,
# so that this logic is easier to handle from here.
# this is a good intercept point to create these, as this is where we will see
# all new contributors.
@create_contributor_record
def createActivity(uid, photo_id, author, action, activity_type):
    a = PhotoActivity(activity_id=uid, photo_id=photo_id)
    a.author=author
    a.activity_content=action
    a.activity_type=activity_type
    a.put()
    return True

def getActivity(activity_id):
    try:
        query = db.Query(PhotoActivity)
        query.filter('activity_id =', activity_id)
        a = query.fetch(limit=1)
        return a[0]
    except:
        return None 

def createPhoto(photoid):
    p = Photo(uid=photoid)
    p.put()
    return p

def getPhoto(photoid):
    try:
        query = db.Query(Photo)
        query.filter('uid =', photoid)
        photo = query.fetch(limit=1)
        return photo[0]
    except:
        return None 

# flickr api calls

def genPhotoCommentUrl(PhotoId):
    url = "http://api.flickr.com/services/rest/?method=flickr.photos.comments.getList&photo_id="+PhotoId+"&api_key="+FLICKRKEY
    return url

def genPhotoInfoUrl(PhotoId):
    url = "http://api.flickr.com/services/rest/?method=flickr.photos.getInfo&photo_id="+PhotoId+"&api_key="+FLICKRKEY
    return url

def genPhotoSizeQueryUrl(PhotoId):
    url = "http://api.flickr.com/services/rest/?method=flickr.photos.getSizes&photo_id="+PhotoId+"&api_key="+FLICKRKEY
    return url

def genGroupPhotoQueryUrl():
    url = 'http://api.flickr.com/services/rest/?method=flickr.groups.pools.getPhotos&group_id='+GROUPID+'&api_key='+FLICKRKEY
    return url

# xml response

def getResponseFromUrl(url):
    result = urlfetch.fetch(url,headers = {'Cache-Control' : 'max-age=300'})        
    if result.status_code == 200:
        return result.content
    else:
        return False

# model setters and getters

def genPhotoImageLink(server, uid, secret):
    photoimage_url = "http://farm5.static.flickr.com/"+server+"/"+uid+"_"+secret+"_m.jpg"
    return photoimage_url

def genPhotoThumbLink(server, uid, secret):
    photothumb_url = "http://farm5.static.flickr.com/"+server+"/"+uid+"_"+secret+"_t.jpg"
    return photothumb_url

def genPhotoPageLink(owner, uid):
    photopage_url = "http://www.flickr.com/photos/"+owner+"/"+uid
    return photopage_url

# get and set image data

def fillinPhotoDetails(photo_xml):
    "this is our fist act of creating the photo object"
    uid = photo_xml.getAttribute("id")
    owner = photo_xml.getAttribute("owner")
    server = photo_xml.getAttribute("server")
    secret = photo_xml.getAttribute("secret")
    title = photo_xml.getAttribute("title")
    ownername = photo_xml.getAttribute("ownername")
    photopage_url = genPhotoPageLink(owner, uid)
    photoimage_url = genPhotoImageLink(server, uid, secret)
    photothumb_url = genPhotoThumbLink(server, uid, secret)
    #
    photo = createPhoto(uid)
    photo.owner_id = owner
    photo.owner_name = ownername
    photo.photopage_url = photopage_url
    photo.photoimage_url = photoimage_url
    photo.photothumb_url = photothumb_url
    photo.title = title
    photo.last_modified = '' # we don't really know, we will get activity later, but we need to zero this
    photo.put()
    
def parsePhotosFromGroupResponse(response):
    xml = minidom.parseString(response)
    photos_xml = xml.getElementsByTagName('photo')
    uids = []
    for photo_xml in photos_xml:
        # get the photoid
        uid = photo_xml.getAttribute("id")
        # check to see if the photoid is in our local database
        photo = getPhoto(uid)
        # if the picture is there, then don't do anything
        if photo:
            continue
        # otherwise create a picture object and add it to the datastore
        else:
            #createPhoto(uid)
            fillinPhotoDetails(photo_xml)
            uids.append(uid)
    if len(uids) == 0:
        return None
    return uids
         
class ListPhotos(webapp.RequestHandler):
    "list images that we have already retrieved from a flickr group"
    def get(self):
    
        query = Photo.all()
        pictures = query.fetch(1000) # could impliment paging here, but not yet
        picturenumber = len(pictures)
        #stored_uids = []
        #for picture in pictures:
        #    stored_uids.append(picture.uid)
        template_values = {'count':picturenumber, 'pictures':pictures}
        path = os.path.join(os.path.dirname(__file__), 'ListPhotos.html')
        self.response.out.write(template.render(path, template_values))

def genPhotoAddActivityFromPhotoUID(uid):
    "if someone has added a picture to the group this should be recorded as an activity"
    photo = getPhoto(uid)
    author = photo.owner_id
    action = "added photo"
    activity_type = "photo"
    createActivity(uid, uid, author, action, activity_type)    
    return True

def genPhotoAddActivitiesFromPhotoUIDs(uids):
    if uids is not None:
        "if someone has added a picture to the group this should be recorded as an activity"
        for uid in uids:
            genPhotoAddActivityFromPhotoUID(uid)
    else:
        return None

class GetPhotos(webapp.RequestHandler):
    "retreive a list of photos from a flickr group, and store new images"
    def get(self):
    
        url = genGroupPhotoQueryUrl()

        response = getResponseFromUrl(url) 
        if response:
            uids = parsePhotosFromGroupResponse(response)
            # might not find any new images, so the next function has to be able to 
            # deal with None as a return type
            genPhotoAddActivitiesFromPhotoUIDs(uids)
        else:
            uids = "no new photos were found"
        if uids == None:
            uids = "no new photos were found"
    
    
        template_values = {'photoids': uids}
        path = os.path.join(os.path.dirname(__file__), 'GetPhotos.html')
        self.response.out.write(template.render(path, template_values))
        
# photo parsing

def parsePhotoInfoResponse(response):
    xml = minidom.parseString(response)
    dates_xml = xml.getElementsByTagName('dates')
    remote_last_modified = dates_xml[0].getAttribute("lastupdate") # I don't know why I need the [0] here
    return remote_last_modified

def getLastModifiedTime(PhotoId):
    url = genPhotoInfoUrl(PhotoId)
    response = getResponseFromUrl(url)
    if response:
        remote_last_modified = parsePhotoInfoResponse(response)
        return remote_last_modified, response
    else:
        return None 

# get and set photo activity 


def extractActivity(PhotoId, photo_info, activity_type):
    "need to change the iter names in this function to be more genaric"
    new_activity_ids = []
    photo_info_xml = minidom.parseString(photo_info)
    tags = photo_info_xml.getElementsByTagName(activity_type)
    for tag in tags:
        activity_id = tag.getAttribute("id")
        activity = getActivity(activity_id)
        if not activity:
            activity_author = tag.getAttribute("author")
            tagtext = tag.firstChild.nodeValue # first child is the text in the tag, doh!
            createActivity(activity_id, PhotoId, activity_author, tagtext, activity_type)
            new_activity_ids.append(activity_id)
        else:
            continue
    return new_activity_ids

def getPhotoCommentsXML(PhotoId):
    url = genPhotoCommentUrl(PhotoId)
    comments_xml = getResponseFromUrl(url)
    return comments_xml
    
def CreatePhotoActivity(PhotoId, photo_info_xml):
    new_activity_ids = []
    # tag activity
    new_activity_ids.extend(extractActivity(PhotoId, photo_info_xml, "tag"))
    # notes activity
    new_activity_ids.extend(extractActivity(PhotoId, photo_info_xml, "note"))
    # comment activity
    comment_xml = getPhotoCommentsXML(PhotoId)
    new_activity_ids.extend(extractActivity(PhotoId, comment_xml, "comment"))
    return new_activity_ids     

def newPhotoActivity(PhotoId):
    new_activity = []
    photo = getPhoto(PhotoId)
    if photo:
        local_last_modified = photo.last_modified
        remote_last_modified, photo_info_xml = getLastModifiedTime(PhotoId)
        if remote_last_modified > local_last_modified:
            # update local last modified time
            photo.last_modified = remote_last_modified
            photo.put()
            message = 'yay, I have found some new activity on that photo'
            new_activity = CreatePhotoActivity(PhotoId, photo_info_xml)
            # now we parse photo_info_xml to get some activity data
            # get the activity on the photo
        else:
            new_activity = []
    else:
        new_activity = []
    return new_activity

class GetNewPhotoActivity(webapp.RequestHandler):
    def get(self, PhotoId):
        photo = getPhoto(PhotoId)
        new_activity = newPhotoActivity(PhotoId)
        template_values = {'photo':photo,'photoid': PhotoId, 'activity':new_activity}
        path = os.path.join(os.path.dirname(__file__), 'GetPhotoActivity.html')
        self.response.out.write(template.render(path, template_values))

class UpdateAllPhotoActivity(webapp.RequestHandler):
    def get(self):
        query = Photo.all()
        photos = query.fetch(FETCHLIMIT)
        updates = []
        for photo in photos:
            new_activity = newPhotoActivity(photo.uid)
            if new_activity: updates.append([photo.uid, new_activity])
        
        template_values = {'updates':updates}
        path = os.path.join(os.path.dirname(__file__), 'ShowAllUpdates.html')
        self.response.out.write(template.render(path, template_values))

def getLocalPhotoActivity(PhotoId):
    q = db.GqlQuery("SELECT * FROM PhotoActivity WHERE photo_id = :1", PhotoId)
    results = q.fetch(FETCHLIMIT)
    return results

class ShowStoredPhotoActivity(webapp.RequestHandler):
    def get(self, PhotoId):
        activities = getLocalPhotoActivity(PhotoId)
        photo = getPhoto(PhotoId)
        template_values = {'photo':photo ,'photoid': PhotoId, 'activities': activities}
        path = os.path.join(os.path.dirname(__file__), 'ShowPhotoActivity.html')
        self.response.out.write(template.render(path, template_values))

class ListActivities(webapp.RequestHandler):
    def get(self):
        query = PhotoActivity.all()
        query.order("-__key__") #chronological reverse order
        activities = query.fetch(PAGINGLIMIT+1)
        
        # some code for paging
        # taken from http://code.google.com/appengine/articles/paging.html
        forward = self.request.get("next")
        back = self.request.get("previous")
        newest = self.request.get("newest") 
        oldest = self.request.get("oldest")  

        if forward:
            activities = PhotoActivity.all().order("-__key__").filter('__key__ <=', db.Key(forward)).fetch(PAGINGLIMIT+1)
        elif back:
            activities = PhotoActivity.all().order("__key__").filter('__key__ >=', db.Key(back)).fetch(PAGINGLIMIT+1)
            activities.reverse()
        elif newest:
            activities = PhotoActivity.all().order("-__key__").fetch(PAGINGLIMIT+1)
        elif oldest:
            activities = PhotoActivity.all().order("__key__").fetch(PAGINGLIMIT) # not seeking extras, we know this is the end  
            activities.reverse()
        else:
            activities = PhotoActivity.all().order("-__key__").fetch(PAGINGLIMIT+1)
            
        # we need to get the key of the very last item in the results set, if that is in our 
        # set that we are showing, then we don't display a previous link
        next = None
        previous = None 
        query = PhotoActivity.all()
        query.order("-__key__") #chronological reverse order
        first_activity_key = query.fetch(1)[0].key()

        previous = activities[0].key()
        if previous == first_activity_key: previous = None 

        # if we skip to the end, and there are not modulo page number results, when we iterate backwards
        # we will end up with a situation in which we get less that the page set, yet we will be at the start, so
        # we need another check here.
        next = activities[0].key()
        if len(activities) == PAGINGLIMIT+1 or next == first_activity_key:
            next = activities[-1].key()
            activities = activities[:PAGINGLIMIT]
        else:
            next = None 
        
        # do a join over activities and photos!
        activiies_photolinks = []
        for activity in activities:
            photo = getPhoto(activity.photo_id)
            photopage_url = photo.photopage_url
            photothumb_url = photo.photothumb_url
            activiies_photolinks.append((activity, photopage_url, photothumb_url))
        
        # find out if current user is an admin
        admin = None 
        if users.get_current_user():
            user = users.get_current_user()
            nickname = user.nickname()
            if users.is_current_user_admin():
                admin = nickname
        
        activity_number = PhotoActivity.all().count()
        template_values = {'count':activity_number, 'activities':activiies_photolinks, 'next':next, 'previous':previous, 'admin':admin}
        path = os.path.join(os.path.dirname(__file__), 'ListActivities.html')
        self.response.out.write(template.render(path, template_values))


class ListUnvoted(webapp.RequestHandler):
    "activities that have no votes yet"
    def get(self):
        query = PhotoActivity.all()
        query.filter("vote_count =", 0)
        query.order("-__key__") #chronological reverse order
        activities = query.fetch(PAGINGLIMIT+1)
        
        # some code for paging
        # taken from http://code.google.com/appengine/articles/paging.html
        forward = self.request.get("next")
        back = self.request.get("previous")
        newest = self.request.get("newest") 
        oldest = self.request.get("oldest")  

        if forward:
            activities = PhotoActivity.all().order("-__key__").filter("vote_count =", 0).filter('__key__ <=', db.Key(forward)).fetch(PAGINGLIMIT+1)
        elif back:
            activities = PhotoActivity.all().order("__key__").filter("vote_count =", 0).filter('__key__ >=', db.Key(back)).fetch(PAGINGLIMIT+1)
            activities.reverse()
        elif newest:
            activities = PhotoActivity.all().order("-__key__").filter("vote_count =", 0).fetch(PAGINGLIMIT+1)
        elif oldest:
            activities = PhotoActivity.all().order("__key__").filter("vote_count =", 0).fetch(PAGINGLIMIT) # not seeking extras, we know this is the end  
            activities.reverse()
        else:
            activities = PhotoActivity.all().order("-__key__").filter("vote_count =", 0).fetch(PAGINGLIMIT+1)
            
        # we need to get the key of the very last item in the results set, if that is in our 
        # set that we are showing, then we don't display a previous link
        next = None
        previous = None 
        query = PhotoActivity.all()
        query.order("-__key__") #chronological reverse order
        query.filter("vote_count =", 0)
        first_activity_key = query.fetch(1)[0].key()

        previous = activities[0].key()
        if previous == first_activity_key: previous = None 

        # if we skip to the end, and there are not modulo page number results, when we iterate backwards
        # we will end up with a situation in which we get less that the page set, yet we will be at the start, so
        # we need another check here.
        next = activities[0].key()
        if len(activities) == PAGINGLIMIT+1 or next == first_activity_key:
            next = activities[-1].key()
            activities = activities[:PAGINGLIMIT]
        else:
            next = None 
        
        # do a join over activities and photos!
        activiies_photolinks = []
        for activity in activities:
            photo = getPhoto(activity.photo_id)
            photopage_url = photo.photopage_url
            photothumb_url = photo.photothumb_url
            activiies_photolinks.append((activity, photopage_url, photothumb_url))
        
        # find out if current user is an admin
        admin = None 
        if users.get_current_user():
            user = users.get_current_user()
            nickname = user.nickname()
            if users.is_current_user_admin():
                admin = nickname
        
        activity_number = PhotoActivity.all().count()
        template_values = {'count':activity_number, 'activities':activiies_photolinks, 'next':next, 'previous':previous, 'admin':admin}
        path = os.path.join(os.path.dirname(__file__), 'ListUnvoted.html')
        self.response.out.write(template.render(path, template_values))

# active actors

class ActorVotes(webapp.RequestHandler):
    def get(self, ActorId):
        template_values = {}
        path = os.path.join(os.path.dirname(__file__), 'ActorVotes.html')
        self.response.out.write(template.render(path, template_values))

def getActorItems(ActorIDInput, itemtype):
    #q = db.GqlQuery("SELECT * FROM PhotoActivity WHERE author = :1",  ActorID)
    ActorID = ActorIDInput.replace("%40", "@") # dirty filthy hack, the @ gets encoded as it's passed in via url parameter!
    a = PhotoActivity.all()
    a.filter("author =", ActorID)
    a.filter("activity_type =", itemtype)
    a.order("-created")
    results = a.fetch(FETCHLIMIT)
    return results

def getActorPhotos(ActorID):
    actor_photos = getActorItems(ActorID, "photo")  
    return actor_photos

def getActorTags(ActorID):
    actor_tags = getActorItems(ActorID, "tag")    

    return actor_tags

def getActorNotes(ActorID):
    actor_notes = getActorItems(ActorID, "note")    
    return actor_notes
    
def getActorComments(ActorID):
    actor_comments = getActorItems(ActorID, "comment")    
    return actor_comments    

def getActorVotesHistory(ActorID):
    v  = Vote.all()
    v.filter("recipient =", ActorID)
    v.order("-created")
    vote_history = v.fetch(FETCHLIMIT)
    return vote_history    
    
class ActorPictures(webapp.RequestHandler):
    def get(self, ActorId):
        actor_photos = getActorPhotos(ActorId)
        ActorIDInput= ActorId.replace("%40", "@")
        template_values = {'actor_photos':actor_photos, 'actor_id':ActorIDInput}
        path = os.path.join(os.path.dirname(__file__), 'ActorPictures.html')
        self.response.out.write(template.render(path, template_values))

class ActorActivity(webapp.RequestHandler):
    def get(self, uid):

        actor_photos = getActorPhotos(ActorId)
        actor_notes = getActorNotes(uid)
        actor_comments = getActorComments(uid)
        actor_tags = getActorTags(uid)
        vote_history = getActorVotesHistory(uid)\
        
        # get the photo objects, rather than just their ids, so we can display links to the images
        photos = []
        for actor_photo in actor_photos:
            photo_id = actor_photo.photo_id
            photos.append(getPhoto(photo_id))
        
        template_values = {'actor_notes':actor_notes, 'actor_comments':actor_comments, 'actor_tags':actor_tags, 'actor_id': uid, 'actor_photos':photos, 'votes':vote_history}
        path = os.path.join(os.path.dirname(__file__), 'ActorActivity.html')
        self.response.out.write(template.render(path, template_values))
        
class ActorReport(webapp.RequestHandler):
    def get(self, ActorIdInput):


        ActorId = ActorIdInput.replace("%40", "@")
    
        actor_photos = getActorPhotos(ActorId)
        actor_notes = getActorNotes(ActorId)
        actor_comments = getActorComments(ActorId)
        actor_tags = getActorTags(ActorId)
        vote_history = getActorVotesHistory(ActorId)
        
        actor = getUniqueContributor(ActorId)
        
        # get the photo objects, rather than just their ids, so we can display links to the images
        photos = []
        for actor_photo in actor_photos:
            photo_id = actor_photo.photo_id
            photos.append(getPhoto(photo_id))
        
        template_values = {'actor_notes':actor_notes, 'actor_comments':actor_comments, 'actor_tags':actor_tags, 'actor_id': ActorId, 'actor_photos':photos, 'votes':vote_history, 'actor': actor}
    
        path = os.path.join(os.path.dirname(__file__), 'ActorReport.html')
        self.response.out.write(template.render(path, template_values))
        
def locallyStoredActors():
    query = UniqueContributors.all()
    query.order("-last_activity_date") 
    actors = query.fetch(FETCHLIMIT)
    return actors

def locallyStoredActorsVoteRanked():
    query = UniqueContributors.all()
    query.order("-vote_sum") 
    actors = query.fetch(FETCHLIMIT)
    return actors
        
class ShowActors(webapp.RequestHandler):
    def get(self):
        actors = locallyStoredActors()
        template_values = {"actors":actors}
        path = os.path.join(os.path.dirname(__file__), 'ShowActors.html')
        self.response.out.write(template.render(path, template_values))

# votes
def set_activity_votes(target):
    "when an activity gets voted on set a flag, so we can easily find activities with no votes"
    def wrapper(*args, **kwargs):
        activity_id = args[1]
        vote_value = args[2]
        activity = getActivity(activity_id)
        if activity:
            activity.vote_count = activity.vote_count + 1
            activity.vote_sum = activity.vote_sum + vote_value
            activity.put()
            return target(*args, **kwargs)
    return wrapper

def set_contributor_votes(target):
    "when an activity gets voted on set a flag, so we can easily find activities with no votes"
    def wrapper(*args, **kwargs):
        actor = args[0]
        vote_value = args[2]
        actor = getUniqueContributor(actor)
        if actor:
            actor.vote_count = actor.vote_count + 1
            actor.vote_sum = actor.vote_sum + vote_value
            actor.put()
            return target(*args, **kwargs)
    return wrapper

def get_activity_votes(activityid):
    activity = getActivity(activityid)
    vote_count = activity.vote_count 
    vote_sum = activity.vote_sum
    return vote_count, vote_sum   

@set_contributor_votes
@set_activity_votes
def createVote(actor, activityid, vote_value):
    user = users.get_current_user()
    v = Vote()
    v.value = v.value + vote_value
    v.activity_id = activityid
    v.recipient = actor
    v.voter = user.nickname()
    v.put()
    return None

class VoteUp(webapp.RequestHandler):
    "using post as we intend to update the vote records"
    def post(self):
        actor = self.request.get('actor')
        activityid = self.request.get('activityid')
        #
        vote_value = 1
        createVote(actor, activityid, vote_value)
        #
        template_values = {"actor":actor, "activity":activityid}
        path = os.path.join(os.path.dirname(__file__), 'voteup.html')
        self.response.out.write(template.render(path, template_values))

class VoteDown(webapp.RequestHandler):
    "using post as we intend to update the vote records"
    def post(self):
        actor = self.request.get('actor')
        activityid = self.request.get('activityid')
        #
        vote_value = -1
        createVote(actor, activityid, vote_value)
        #
        template_values = {"actor":actor, "activity":activityid}
        path = os.path.join(os.path.dirname(__file__), 'votedown.html')
        self.response.out.write(template.render(path, template_values))

class RpcVoteUp(webapp.RequestHandler):
    "using post as we intend to update the vote records"
    def post(self):
        actor = self.request.get('actor')
        activityid = self.request.get('activityid')
        #
        vote_value = 1
        createVote(actor, activityid, vote_value)
        #
        vote_count, vote_sum = get_activity_votes(activityid)
        message = "yay! you voted"
        response = {'message':message, 'sum': vote_sum, 'count': vote_count}
        self.response.out.write(simplejson.dumps(response))
        
class RpcVoteDown(webapp.RequestHandler):
    "using post as we intend to update the vote records"
    def post(self):
        actor = self.request.get('actor')
        activityid = self.request.get('activityid')
        #
        vote_value = -1
        createVote(actor, activityid, vote_value)
        #
        vote_count, vote_sum = get_activity_votes(activityid)
        message = "yay! you voted"
        response = {'message':message, 'sum': vote_sum, 'count': vote_count}
        self.response.out.write(simplejson.dumps(response))
        
class LeagueTable(webapp.RequestHandler):
    def get(self):
        actors = locallyStoredActorsVoteRanked()
        template_values = {"actors":actors}
        path = os.path.join(os.path.dirname(__file__), 'LeagueTable.html')
        self.response.out.write(template.render(path, template_values))


# queuing

class LoadQueues(webapp.RequestHandler):
    def get(self):
        # Add the task to the default queue.
        photosq = taskqueue.Queue(name='photosq')
        phototask = taskqueue.Task(url='/getphotos/', method='GET')
        photosq.add(phototask)
        
        #monitor = TaskMonitor()
        #monitor.queue = "placed new photo check"
        #monitor.put()

        query = Photo.all()
        query.order("-last_modified") 
        photos = query.fetch(FETCHLIMIT)
        activityq = taskqueue.Queue(name='activityq') 
        for photo in photos:        
            worker_url = "/photo/getactivity/" + photo.uid
            activitytask = taskqueue.Task(url=worker_url, method='GET')  
            activityq.add(activitytask)          

        #monitor = TaskMonitor()
        #monitor.queue = "placed photo activites check"
        #monitor.put()
        
        return True
        # ok let's see what happens with the queuing!
        # self.redirect('/')
        
# simple pages:s

class Advanced(webapp.RequestHandler):
    def get(self):
        template_values = {}
        path = os.path.join(os.path.dirname(__file__), 'advanced.html')
        self.response.out.write(template.render(path, template_values))

class Instructions(webapp.RequestHandler):
    def get(self):
        template_values = {}
        path = os.path.join(os.path.dirname(__file__), 'Instructions.html')
        self.response.out.write(template.render(path, template_values))

# main page

class MainHandler(webapp.RequestHandler):
    def get(self):

        if users.get_current_user():
            user = users.get_current_user()
            nickname = user.nickname()
            url = users.create_logout_url(self.request.uri)
            url_linktext = 'Logout'
            if users.is_current_user_admin():
                admin_url = "/admin/"
                admin_linktext = "admin"
            else:
                admin_url = None 
                admin_linktext = None                 
        else:
            admin_url = None 
            admin_linktext = None                             
            nickname = None 
            url = users.create_login_url(self.request.uri)
            url_linktext = 'Login'

        template_values = {
            'nickname': nickname,
            'url': url,
            'url_linktext': url_linktext,
            'admin_url': admin_url,
            'admin_linktext' : admin_linktext
            }

        path = os.path.join(os.path.dirname(__file__), 'index.html')
        self.response.out.write(template.render(path, template_values))

def main():
    application = webapp.WSGIApplication([('/', MainHandler),
                                          ('/enginestart', LoadQueues),
                                          ('/photo/getactivity/(.*)', GetNewPhotoActivity),
                                          ('/photo/showactivity/(.*)', ShowStoredPhotoActivity),   
                                          ('/actor/votesreceived/(.*)', ActorVotes),
                                          ('/actor/pictures/(.*)', ActorPictures),   
                                          ('/actor/activity/(.*)', ActorActivity),   
                                          ('/actor/report/(.*)', ActorReport),   
                                          ('/showactors/', ShowActors),   
                                          ('/increment', VoteUp),                                             
                                          ('/decrement', VoteDown),
                                          ('/rpcincrement', RpcVoteUp),                                             
                                          ('/rpcdecrement', RpcVoteDown),
                                          ('/leaguetable/', LeagueTable),                                              
                                          ('/getupdates/', UpdateAllPhotoActivity),   
                                          ('/getphotos/', GetPhotos),
                                          ('/listactivities/', ListActivities),
                                          ('/listunvoted/', ListUnvoted),
                                          ('/advanced/', Advanced),
                                          ('/instructions/', Instructions),
                                          ('/listphotos/', ListPhotos)], debug=True)
                                          
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()
    
