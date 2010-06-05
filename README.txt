# About.

flickr-voter is a small appengine web app for monitoring social activity within a flickr group. It allows admins of the application to vote on the activity that happens in the group, and provides a league table of people who have contributed to a group. 

The code uses a cron job to trigger task queues that look for new activity on the flickr group. 

# Installation

- Grab the latest code from github http://github.com/IanMulvany/flickr-voter
- get yourself a google appengine account http://code.google.com/appengine/
- get yourself a flickr api key http://www.flickr.com/services/api/misc.api_keys.html
- mv config-example.py to config.py and enter your api key and id of the group you want to track
- upload your code to your appengine account
- have fun!

To turn off the applicaiton, upload a new queue.yaml with all queues set to not trigger, and upload a new empty cron.yaml.
To empty your datastores you will have to do that from you appengine console.

You can add new administrators to the app from the google admin console, more info here: http://code.google.com/appengine/docs/theadminconsole.html. You will have to give them full access to the application. 
