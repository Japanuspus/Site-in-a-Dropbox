import unittest
from siteinadropbox.metadataparser import parse_metadata

abstract="""\
First continuation line
Second continuation line
  and a third, indented\
"""
body="""\
Behold: The first content line.
The second content line.
"""

MMDa="""\
Title: The Title
Author: The Man
Abstract:
  First continuation line
  Second continuation line
    and a third, indented

"""+body

MMDb="""\
The Title
---------
Author: The Man
Abstract: First continuation line
  Second continuation line
    and a third, indented

"""+body

RSTa="""\
The Title
---------
:Author: The Man
:Abstract: First continuation line
  Second continuation line
    and a third, indented

"""+body

RSTb="""\
=========
The Title
========= 
:Author: The Man
:Abstract: First continuation line
  Second continuation line
    and a third, indented

"""+body

class PassTestCase(unittest.TestCase):
    def check_response(self,p):
        pk=set(p.keys())
        sk=set(self.expected.keys())
        self.assertEqual(pk,sk)
        for k in pk.union(sk):
            self.assertEqual(p[k], self.expected[k])

class FullPassTestCase(PassTestCase):
    def setUp(self):
        self.expected={
            'title':'The Title',
            'abstract':abstract,
            'author':'The Man',
            'body':body,
            }
    def test_MMDa(self):
        self.check_response(parse_metadata(MMDa))
    def test_MMDb(self):
        self.check_response(parse_metadata(MMDb))
    def test_RSTa(self):
        self.check_response(parse_metadata(RSTa))
    def test_RSTb(self):
        self.check_response(parse_metadata(RSTb))

class BodyOnlyTestCase(PassTestCase):
    def setUp(self):
        self.expected={'body': body}
    def test_body(self):
        self.check_response(parse_metadata(body))


fail_bad_title="""\
------
title
author: me
"""
fail_bad_indent="""\
abstract:
    first abstract line
  second abstract line
"""

class ErrorTestCase(unittest.TestCase):
    def test_bad_title(self):
        self.assertRaises(Exception,parse_metadata,fail_bad_title)
    def test_bad_indent(self):
        self.assertRaises(Exception,parse_metadata,fail_bad_indent)
                                  
suite=unittest.TestSuite([unittest.TestLoader().loadTestsFromTestCase(c) for c in [
        FullPassTestCase, BodyOnlyTestCase, ErrorTestCase
        ]])

if __name__=='__main__':
    unittest.TextTestRunner(verbosity=2).run(suite)
