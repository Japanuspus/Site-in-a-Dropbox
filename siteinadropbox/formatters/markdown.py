from __future__ import absolute_import

import markdown2
from siteinadropbox import metadataparser

def get_formatter():
    return Formatter()

class Formatter(object):
    def __init__(self):
        self.markdowner = markdown2.Markdown(extras='smarty-pants')
        self.mdparser = metadataparser.MetadataParser()

    def format(self, source, default_attributes):
        if default_attributes is None:
            md = {}
        else:
            md=default_attributes.copy()
        newmd = self.mdparser.parse(source)
        source_body = newmd.pop('body')
        md.update(newmd)
        md['body'] = self.markdowner.convert(source_body)
        return  md
    
