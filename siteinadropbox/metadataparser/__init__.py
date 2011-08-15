"""
metadataparser is designed to read metadata fields from light markup
pages in a way that is compatible with docutils [bibinfo][rst] fields as
well as  Multimarkdown's [multimarkdown][metadata fields].
To do so, we follow the markup-specification of [multimarkdown] with the
additions that
- a colon can be added before the field key
- lines matching a docinfo title will be mapped to the title field

In other words, these headers are both valid
=======
A Title
=======
:author: foo

title: A Title
author: foo

Multimarkdown recommends these fields:
- Title
- Author
- Date

ReStructuredText has these fields:
- Author
- Version
- Status
- Date
- Abstract

Site in a dropbox should use:
-----------------------------
Author   Some name <some@name.nil>
Title     
Date
Format   Markdown | Restructuredtext | ...
Markdown_options 

Author should be split to 'author' and 'author_email' if an email is presented in () or <>

[multimarkdown]: http://fletcher.github.com/peg-multimarkdown/
[rst]: http://docutils.sourceforge.net/docs/ref/rst/restructuredtext.html#bibliographic-fields

"""

import re
import itertools
import logging
logging.getLogger().setLevel(logging.DEBUG)

allowed_section_symbols=r""""!#$%&'()*+,-./:;<=>?@[\]_`{|}~"""
key_value=re.compile(r':?(?P<key>[\w-]+):\s*(?P<value>.*)$')

def is_section_line(line):
    """Return s[0] if s is composed of identical allowed section separator symbols"""
    if (line and line[0] in allowed_section_symbols 
        and all(s==line[0] for s in line.strip())):
        return line[0]

def indent_count(s, tabwidth=4):
    """
    Return (<indent>,<content>) 
    """
    leading_whitespace_lengths=[
        ((c==' ' and 1) or tabwidth) for c in itertools.takewhile(lambda t: t in ' \t',s)]
    return (sum(leading_whitespace_lengths), s[len(leading_whitespace_lengths):])

class MetadataParser(object):
    def __init__(self):
        pass

    def look(self,n=0):
        if self.ptr+n<len(self.txt):
            return self.txt[self.ptr+n]
    def consume(self):
        if self.ptr<len(self.txt):
            self.ptr+=1
            return self.txt[self.ptr-1]
        else:
            raise Exception('Bug in metadataparser: consume called with no content left')
    def rest(self):
        """Skips current line if blank. Returns [] if no lines left."""
        if self.ptr<len(self.txt) and not self.look().strip():
            self.consume()
        return self.txt[self.ptr:]
    
    def lineno(self):
        return self.ptr+1
    def debugstr(self):
        return 'line %3d: %s'%(self.lineno(),self.look())

    def resttitle(self):
        sym1=is_section_line(self.look(0))
        if sym1:
            self.consume()
        if is_section_line(self.look(1)):
            self.fields['Title']=self.consume()
            self.consume()
        elif sym1:
            raise Exception('Malformed title field\n %s'%'\n'.join(self.txt[0:3]))
        return self.keyvalue
    
    def keyvalue(self):
        m=key_value.match(self.look())
        if not m:
            if 'Title' in self.fields:
                raise Exception('Line %d: Line directly after valid RST-style title is not valid\
                metadata key,value pair. Insert empty line?'%self.lineno())
            else:
                #We are in a regular paragraph: There is no metadata!
                self.fields={}
                self.ptr=0
                return None
        self.consume()
        key, val = m.group('key','value')

        # Now start looking for continuation lines -- really another state?
        indent, content = indent_count(self.look())
        firstindent=indent
        while indent:
            self.consume()
            if indent<firstindent:
                raise Exception('Line %d: Decreasing indent in continuation lines'%self.lineno())
            if len(val.strip())==0:
                val = ' '*(indent-firstindent)+content
            else:
                val+='\n'+' '*(indent-firstindent)+content
            indent, content = indent_count(self.look())

        self.fields[key.lower().strip()]=val
        return self.keyvalue

    def parse(self,s):
        if type(s)!=list:
            self.txt=s.split('\n')
        else:
            self.txt=s
        self.ptr=0
        self.fields={}

        nextfield=self.resttitle
        while nextfield and self.look(0) and self.look(0).strip():
            nextfield=nextfield()
        if 'Title' in self.fields:
            # Title is an RST style title
            self.fields['title']=self.fields['Title']
            del(self.fields['Title'])

        body='\n'.join(self.rest())
        self.fields['body']=body
        return self.fields 

def parse_metadata(string_or_strings):
    """
    Parse a file for metadata headers.
    txt can be a string with embedded newlines or a list of lines.
    Returns a dictionary with body in the 'body' field.
    """
    o=MetadataParser()
    return o.parse(string_or_strings)
