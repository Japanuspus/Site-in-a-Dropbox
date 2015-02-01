Site in a Dropbox
=================
Site in a Dropbox is a Google App Engine application, providing a web host backed by Dropbox. The application is not associated with Google or Dropbox.

Features
--------
The key idea of Site in a Dropbox, is that it should be an modernized version of the venerable static file webserver: It uses a traditional file system as a (read only) database, and then performs a lot of fomatting. 
Pages can be composed in Markdown, ReST, or HTML, and metadata (dates, tags, etc.) is automatically extracted. The pages are presented via Django templates which can also just be uploaded to the Dropbox. 

Working installations
---------------------
I have working installations at [siteinadropbox.appspot.com](http://siteinadropbox.appspot.com) and [demo.insignificancegalore.net](http://demo.insignificancegalore.net). As I am still awaiting Dropbox approval for a general release of the service, my installation can only host files from my own Dropbox.

Custom domains
--------------
The application can serve multiple domains from a single installation. Custom domains need to be registered with [Google Apps](http://www.google.com/apps/intl/en/group/index.html), after which the `siteinadropbox` Google App Engine service can be added from the dashboard.  


Service hosted by by Google App Engine
(c) Janus <janus@insignificancegalore.net>, 2011

