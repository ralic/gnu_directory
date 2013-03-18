# encoding: utf8

import datetime
import re
import sys
import textwrap

import numpy
import pandas as pd

import license

download_keys = """
    Origin
    Original-Source
    Source
    Source-Code
    X-Origin
    X-Original-Package
    X-Source
    """

def concat(xss):
    all = []

    for xs in xss:
        all.extend(xs)

    return all

def today():
    return datetime.datetime.now().strftime('%Y-%m-%d')

def warn(*x):
    print >>sys.stderr, ('warning:',) + x

class PkgData(object):
    def __init__(self):
        pkg_store = pd.HDFStore('pkg.h5')
        self.pkgs = pkg_store['packages']
        self.descs = pkg_store['descriptions']
        pkg_store.close()

        cp_store = pd.HDFStore('cp.h5')
        self.cpf = cp_store['cp_files']
        self.cps = cp_store['cp_summary']
        cp_store.close()

class Template(object):
    def __init__(self, name, values):
        self.name = name
        self.values = values

    def __str__(self):
        return '{{%s\n%s\n}}' % (
            self.name,
            '\n'.join(['|' + '%s=%s' %
                (n, v.encode('utf8') if isinstance(v, unicode) else v)
                for (n, v) in self.values]))

def parse_tags(s):
    return s.replace('\n', '').split(', ')

def extract_languages(tags):
    langs = []

    for tag in tags:
        (a, b) = tag.split('::')

        if a == 'implemented-in':
            langs.append(b)
        elif a == 'devel' and b.startswith('lang:'):
            langs.append(b.split(':')[1])

    return list(set(langs))

def munge_description(s):
    paras = s.split('\n .\n')
    return '\n\n'.join(
        textwrap.fill(para.lstrip().replace('\n', ''), 65) for para in paras)

def get_license_map():
    map = {}

    for para in file('license_map').read().split('\n\n'):
        if not para:
            continue

        match = re.match('\[([^\]]+)\]', para)
        assert match, para
        canonical = match.group(1)
        aliases = para[match.end():].lstrip().splitlines()

        for alias in aliases:
            map[alias] = canonical

    return map

def srcpkg_extract_licenses(header, filess):
    # XXX: generate template from header stanza
    # XXX: flag CC licenses
    # XXX: check all License stanzas were included
    lmap = get_license_map()

    for (_ix, files) in filess.iterrows():
        lname = files['_license'].strip()

        if '\n' not in lname:
            # Looks like license text is present.
            txt = files['License']
        else:
            # Licens information is a stub.
            # XXX: look it up
            txt = lname

        canon = lmap.get(lname.lower(), 'Other')
        # XXX: Should maybe bail if there's no copyright field.
        cp = ''.join(
            u'© %s\n' % line
            for line in files.dropna().get('Copyright', '').splitlines())
        cp = cp.encode('utf8')
        txt = txt.encode('utf8')

        yield Template('Project license', [
            ('License', canon),
            ('License note', (cp + '\n' + txt))])

def parse_person(s):
    match = re.match('([^<]+)\s+<([^>]+)>', s)

    if match:
        return (match.group(1), match.group(2))
    else:
        return (s, '')

def extract_people(df):
    # XXX: extract contributors, maintainers
    df = df.dropna()

    if 'Upstream-Contact' in df:
        (name, email) = parse_person(df['Upstream-Contact'])
        yield Template('Person', [
            ('Real name', name),
            ('Role', 'contact'),
            ('Email', email),
            ('Resource URL', '')])

def extract_resources(cp_header):
    cp_header = cp_header.dropna()

    for key in re.findall('\S+', download_keys):
        if key in cp_header:
            yield Template('Resource', [
                ('Resource kind', 'Download'),
                ('Resource URL', cp_header[key])])

def export_srcpkgs(data, name, srcpkg_names):
    binpkgs = pd.concat([
        data.pkgs[data.pkgs['_srcpkg'] == srcpkg]
        for srcpkg in srcpkg_names])

    if len(binpkgs) == 0:
        warn('no binary packages found for', srcpkg_names)
        return

    binpkg_names = sorted(binpkgs['Package'], key=len)
    print binpkg_names
    print list(binpkgs['Package'])
    homepages = list(binpkgs['Homepage'])
    # XXX: maybe choose the one that appears the most?
    homepage = homepages[0] if homepages else ''
    tags = set(concat(
        [parse_tags(t) for t in binpkgs['Tag'] if not pd.isnull(t)]))
    print tags
    langs = [s.title() for s in extract_languages(tags)]
    print langs

    if name in binpkg_names:
        descpkg = name
    else:
        # Heuristic: choose the package with the shortest name.
        # We could try to do something smarter, like look for the common
        # prefix of the descriptions of all the binary packages.
        descpkg = binpkg_names[0]

    desc = list(data.descs[
        data.descs['Package'] == descpkg]['Description-en'])[0]
    (short_desc, full_desc) = desc.split('\n', 1)
    full_desc = munge_description(full_desc)

    print Template('Entry', [
        ('Name', name.capitalize()),
        ('Short description', short_desc),
        ('Full description', full_desc),
        ('Homepage URL', homepage),
        ('User level', ''),
        # XXX get this information from apt-file
        ('Component programs', ''),
        ('VCS checkout command', ''),
        ('Computer languages', ', '.join(langs)),
        ('Status', ''),
        ('Is GNU', 'No'),
        ('Submitted by', 'Debian import'),
        ('Submitted date', today())])

    print Template('Import', [
        ('Source', 'Debian'),
        ('Source link',
            'http://packages.debian.org/sid/' + srcpkg_names[0]),
        ('Date', today())])

    people = []
    res = []

    for srcpkg in srcpkg_names:
        pkg_cps = data.cps[data.cps['_srcpkg'] == srcpkg].ix[0]
        pkg_cpf = data.cpf[data.cpf['_srcpkg'] == srcpkg]
        people.extend(list(extract_people(pkg_cps)))
        res.extend(list(extract_resources(pkg_cps)))
        #licenses = license.parse_licenses(list(pkg_cpf['_license']))
        #licenses = [
        #    license.parse_licenses(row['_license'])
        #    for (_ix, row) in pkg_cpf.iterrows()]
        #print licenses
        #all = set(concat(l.flatten() for l in licenses))

        for template in srcpkg_extract_licenses(pkg_cps, pkg_cpf):
            # XXX: eliminate duplicates
            print template

    for template in people:
        # XXX: eliminate duplicates
        print template

    for template in res:
        # XXX: eliminate duplicates
        print template

    #print Template('Software category', [
    #    ('Resource kind', ''),
    #    ('Resource URL', '')])

def export(data, name):
    pkg_cps = data.cps[data.cps['Upstream-Name'] == name]
    srcpkg_names = list(pkg_cps['_srcpkg'])
    print name
    print 'source packages:', srcpkg_names
    export_srcpkgs(data, name, srcpkg_names)

def main():
    data = PkgData()
    args = sys.argv[1:]

    if len(args) == 0:
        unames = set(data.cps['Upstream-Name'].dropna())

        for uname in unames:
            export(data, uname)

        no_uname = set(data.cps[
            data.cps['Upstream-Name'].isnull()]['_srcpkg'])

        for srcpkg in no_uname:
            export_srcpkgs(data, srcpkg, [srcpkg])
    elif len(args) == 1:
        export(data, args[0])
    else:
        raise RuntimeError()

if __name__ == '__main__':
    main()

