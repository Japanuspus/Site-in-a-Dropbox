import os.path

from test import dbtools

"""
A-cases test create, update and remove

   A0             A1             A2
  a.txt         a.txt          *a.txt
  b                          
   b1.txt       *b1.txt

B-cases test dir <> file transitions
    B0     B1
  a      a
          a1.txt
  b      b
   b1.txt
"""

def make_fake_client(name):
    filename = os.path.abspath(os.path.join(os.path.split(__file__)[0], name+'.zip'))
    return dbtools.FakeClient(state_zip=filename)
        
def make_fake_site(name):
    return dbtools.FakeSite(make_fake_client(name), base_dir='/Dropsite')

