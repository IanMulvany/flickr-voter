from google.appengine.api import mail
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template
import os

class AdminHandler(webapp.RequestHandler):
    def get(self):
        
        # if we are here, we must be logged in
        user = users.get_current_user()
        nickname = user.nickname()
        url = users.create_logout_url(self.request.uri)
        url_linktext = 'Logout'
        
        template_values = {
            'nickname': nickname,
            'url': url,
            'url_linktext': url_linktext,
            }
        
        path = os.path.join(os.path.dirname(__file__), 'admin_overview.html')
        self.response.out.write(template.render(path, template_values))
                
def main():
    application = webapp.WSGIApplication([('/admin/', AdminHandler)],
                                         debug=True)
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()