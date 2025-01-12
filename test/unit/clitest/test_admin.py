#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
   Test of the omero admin control.

   Copyright 2008-2019 Glencoe Software, Inc. All rights reserved.
   Use is subject to license terms supplied in LICENSE.txt

"""

import os
import re
import sys
import pytest

from path import path
from glob import glob

import omero
import omero.clients

from omero.cli import CLI, NonZeroReturnCode
from omero.plugins.admin import AdminControl
from omero.plugins.prefs import PrefsControl

from mocks import MockCLI

omeroDir = path(os.getcwd()) / "build"

GRID_FILES = ["templates.xml", "default.xml", "windefault.xml"]
ETC_FILES = ["ice.config", "master.cfg", "internal.cfg"]

MISSING_CONFIGURATION_MSG = "Missing internal configuration."
REWRITE_MSG = " Run bin/omero admin rewrite."
FORCE_REWRITE_MSG = " Pass --force-rewrite to the command."
OMERODIR = False
if 'OMERODIR' in os.environ:
    OMERODIR = os.environ.get('OMERODIR')


@pytest.fixture(autouse=True)
def tmpadmindir(tmpdir):
    etc_dir = tmpdir.mkdir('etc')
    etc_dir.mkdir('grid')
    tmpdir.mkdir('var')
    templates_dir = etc_dir.mkdir('templates')
    templates_dir.mkdir('grid')

    # Need to know where to find OMERO
    assert 'OMERODIR' in os.environ
    old_etc_dir = os.path.join(OMERODIR, "..", "etc")
    old_templates_dir = os.path.join(old_etc_dir, "templates")
    for f in glob(os.path.join(old_etc_dir, "*.properties")):
        path(f).copy(path(etc_dir))
    for f in glob(os.path.join(old_templates_dir, "*.cfg")):
        path(f).copy(path(templates_dir))
    for f in glob(os.path.join(old_templates_dir, "grid", "*.xml")):
        path(f).copy(path(templates_dir / "grid"))
    path(os.path.join(old_templates_dir, "ice.config")).copy(path(templates_dir))

    return path(tmpdir)


@pytest.mark.skipif(OMERODIR is False, reason="We need $OMERODIR")
class TestAdmin(object):

    @pytest.fixture(autouse=True)
    def setup_method(self, tmpadmindir):
        # Other setup
        self.cli = MockCLI()
        self.cli.dir = tmpadmindir
        self.cli.register("admin", AdminControl, "TEST")
        self.cli.register("config", PrefsControl, "TEST")

    def teardown_method(self, method):
        self.cli.teardown_method(method)

    def invoke(self, string, fails=False):
        try:
            self.cli.invoke(string, strict=True)
            if fails:
                assert False, "Failed to fail"
        except:
            if not fails:
                raise

    def testMain(self):
        try:
            self.invoke("")
        except NonZeroReturnCode:
            # Command-loop not implemented
            pass

    #
    # Async first because simpler
    #

    def XtestStartAsync(self):
        # DISABLED: https://trac.openmicroscopy.org/ome/ticket/10584
        self.cli.addCall(0)
        self.cli.checksIceVersion()
        self.cli.checksStatus(1)  # I.e. not running

        self.invoke("admin startasync")
        self.cli.assertCalled()
        self.cli.assertStderr(
            ['No descriptor given. Using etc/grid/default.xml'])

    def testStopAsyncNoConfig(self):
        self.invoke("admin stopasync", fails=True)
        self.cli.assertStderr([MISSING_CONFIGURATION_MSG + FORCE_REWRITE_MSG])
        self.cli.assertStdout([])

    def testStopAsyncRunning(self):
        self.invoke("admin rewrite")
        self.cli.checksStatus(0)  # I.e. running
        self.cli.addCall(0)
        self.invoke("admin stopasync")
        self.cli.assertStderr([])
        self.cli.assertStdout([])

    def testStopAsyncRunningForceRewrite(self):
        self.cli.checksStatus(0)  # I.e. running
        self.cli.addCall(0)
        self.invoke("admin stopasync --force-rewrite")
        self.cli.assertStderr([])
        self.cli.assertStdout([])

    def testStopAsyncNotRunning(self):
        self.invoke("admin rewrite")
        self.cli.checksStatus(1)  # I.e. not running
        self.invoke("admin stopasync", fails=True)
        self.cli.assertStderr(["Server not running"])
        self.cli.assertStdout([])

    def testStopAsyncNotRunningForceRewrite(self):
        self.cli.checksStatus(1)  # I.e. not running
        self.invoke("admin stopasync --force-rewrite", fails=True)
        self.cli.assertStderr(["Server not running"])
        self.cli.assertStdout([])

    def testStopNoConfig(self):
        self.invoke("admin stop", fails=True)
        self.cli.assertStderr([MISSING_CONFIGURATION_MSG + FORCE_REWRITE_MSG])
        self.cli.assertStdout([])

    def testStopNoConfigForceRewrite(self):
        self.cli.checksStatus(0)  # I.e. running
        self.cli.addCall(0)
        self.cli.checksStatus(1)  # I.e. not running
        self.invoke("admin stop --force-rewrite")
        self.cli.assertStderr([])
        self.cli.assertStdout(['Waiting on shutdown. Use CTRL-C to exit'])

    def testStop(self):
        self.invoke("admin rewrite")
        self.cli.checksStatus(0)  # I.e. running
        self.cli.addCall(0)
        self.cli.checksStatus(1)  # I.e. not running
        self.invoke("admin stop")
        self.cli.assertStderr([])
        self.cli.assertStdout(['Waiting on shutdown. Use CTRL-C to exit'])

    #
    # STATUS
    #

    def testStatusNoConfig(self):
        self.invoke("admin status", fails=True)
        self.cli.assertStderr([MISSING_CONFIGURATION_MSG + REWRITE_MSG])
        self.cli.assertStdout([])

    def testStatusNodeFails(self):

        self.invoke("admin rewrite")

        # Setup the call to bin/omero admin ice node
        popen = self.cli.createPopen()
        popen.wait().AndReturn(1)

        self.cli.mox.ReplayAll()
        pytest.raises(NonZeroReturnCode, self.invoke, "admin status")

    def testStatusSMFails(self):

        self.invoke("admin rewrite")

        # Setup the call to bin/omero admin ice node
        popen = self.cli.createPopen()
        popen.wait().AndReturn(0)

        # Setup the call to session manager
        control = self.cli.controls["admin"]
        control._intcfg = lambda: ""

        def sm(*args):
            raise Exception("unknown")
        control.session_manager = sm

        self.cli.mox.ReplayAll()
        pytest.raises(NonZeroReturnCode, self.invoke, "admin status")

    def testStatusPasses(self, tmpdir, monkeypatch):

        self.invoke("admin rewrite")

        ice_config = tmpdir / 'ice.config'
        ice_config.write('omero.host=localhost\nomero.port=4064')
        monkeypatch.setenv("ICE_CONFIG", ice_config)

        # Setup the call to bin/omero admin ice node
        popen = self.cli.createPopen()
        popen.wait().AndReturn(0)

        # Setup the call to session manager
        control = self.cli.controls["admin"]
        control._intcfg = lambda: ""

        def sm(*args):

            class A(object):
                def create(self, *args):
                    raise omero.WrappedCreateSessionException()
            return A()
        control.session_manager = sm

        self.cli.mox.ReplayAll()
        self.invoke("admin status")
        assert 0 == self.cli.rv


def check_registry(topdir, prefix='', registry=4061, **kwargs):
    for key in ['master.cfg', 'internal.cfg']:
        s = path(topdir / "etc" / key).text()
        assert 'tcp -h 127.0.0.1 -p %s%s' % (prefix, registry) in s


def check_ice_config(topdir, prefix='', ssl=4064, **kwargs):
    config_text = path(topdir / "etc" / "ice.config").text()
    pattern = re.compile('^omero.port=\d+$', re.MULTILINE)
    matches = pattern.findall(config_text)
    assert matches == ["omero.port=%s%s" % (prefix, ssl)]


def check_default_xml(topdir, prefix='', tcp=4063, ssl=4064, ws=4065, wss=4066,
                      transports=None, **kwargs):
    if transports is None:
        transports = ['ssl', 'tcp']
    routerport = (
        '<variable name="ROUTERPORT"    value="%s%s"/>' % (prefix, ssl))
    insecure_routerport = (
        '<variable name="INSECUREROUTER" value="OMERO.Glacier2'
        '/router:tcp -p %s%s -h @omero.host@"/>' % (prefix, tcp))
    client_endpoint_list = []
    for tp in transports:
        if tp == 'tcp':
            client_endpoint_list.append('tcp -p %s%s' % (prefix, tcp))
        if tp == 'ssl':
            client_endpoint_list.append('ssl -p %s%s' % (prefix, ssl))
        if tp == 'ws':
            client_endpoint_list.append('ws -p %s%s' % (prefix, ws))
        if tp == 'wss':
            client_endpoint_list.append('wss -p %s%s' % (prefix, wss))

    client_endpoints = 'client-endpoints="%s"' % ':'.join(client_endpoint_list)
    for key in ['default.xml', 'windefault.xml']:
        s = path(topdir / "etc" / "grid" / key).text()
        assert routerport in s
        assert insecure_routerport in s
        assert client_endpoints in s


def check_templates_xml(topdir, glacier2props):
    s = path(topdir / "etc" / "grid" / "templates.xml").text()
    for k, v in glacier2props:
        expected = '<property name="%s" value="%s" />' % (k, v)
        assert expected in s


@pytest.mark.skipif(OMERODIR is False, reason="We need $OMERODIR")
class TestJvmCfg(object):
    """Test template files regeneration"""

    @pytest.fixture(autouse=True)
    def setup_method(self, tmpadmindir):
        self.cli = CLI()
        self.cli.dir = path(tmpadmindir)
        self.cli.register("admin", AdminControl, "TEST")
        self.cli.register("config", PrefsControl, "TEST")
        self.args = ["admin", "jvmcfg"]

    def testNoTemplatesGeneration(self):
        """Test no template files are generated by the jvmcfg subcommand"""

        # Test non-existence of configuration files
        for f in GRID_FILES:
            assert not os.path.exists(path(self.cli.dir) / "etc" / "grid" / f)
        for f in ETC_FILES:
            assert not os.path.exists(path(self.cli.dir) / "etc" / f)

        # Call the jvmcf command and test file genearation
        self.cli.invoke(self.args, strict=True)
        for f in GRID_FILES:
            assert not os.path.exists(path(self.cli.dir) / "etc" / "grid" / f)
        for f in ETC_FILES:
            assert not os.path.exists(path(self.cli.dir) / "etc" / f)

    @pytest.mark.parametrize(
        'suffix', ['', '.blitz', '.indexer', '.pixeldata', '.repository'])
    def testInvalidJvmCfgStrategy(self, suffix, tmpdir):
        """Test invalid JVM strategy configuration leads to CLI error"""

        key = "omero.jvmcfg.strategy%s" % suffix
        self.cli.invoke(["config", "set", key, "bad"], strict=True)
        with pytest.raises(NonZeroReturnCode):
            self.cli.invoke(self.args, strict=True)


@pytest.mark.skipif(OMERODIR is False, reason="We need $OMERODIR")
class TestRewrite(object):
    """Test template files regeneration"""

    @pytest.fixture(autouse=True)
    def setup_method(self, tmpadmindir):
        self.cli = CLI()
        self.cli.dir = path(tmpadmindir)
        self.cli.register("admin", AdminControl, "TEST")
        self.cli.register("config", PrefsControl, "TEST")
        self.args = ["admin", "rewrite"]

    def testTemplatesGeneration(self):
        """Test template files are generated by the rewrite subcommand"""

        # Test non-existence of configuration files
        for f in GRID_FILES:
            assert not os.path.exists(path(self.cli.dir) / "etc" / "grid" / f)
        for f in ETC_FILES:
            assert not os.path.exists(path(self.cli.dir) / "etc" / f)

        # Call the jvmcf command and test file genearation
        self.cli.invoke(self.args, strict=True)
        for f in GRID_FILES:
            assert os.path.exists(path(self.cli.dir) / "etc" / "grid" / f)
        for f in ETC_FILES:
            assert os.path.exists(path(self.cli.dir) / "etc" / f)

    def testForceRewrite(self, monkeypatch):
        """Test template regeneration while the server is running"""

        # Call the jvmcfg command and test file generation
        self.cli.invoke(self.args, strict=True)
        monkeypatch.setattr(AdminControl, "status", lambda *args, **kwargs: 0)
        with pytest.raises(NonZeroReturnCode):
            self.cli.invoke(self.args, strict=True)

    def testOldTemplates(self):
        old_templates = path(__file__).dirname() / ".." / "old_templates.xml"
        old_templates.copy(
            path(self.cli.dir) / "etc" / "templates" / "grid" /
            "templates.xml")
        with pytest.raises(NonZeroReturnCode):
            self.cli.invoke(self.args, strict=True)

    @pytest.mark.parametrize('prefix', [None, 1])
    @pytest.mark.parametrize('registry', [None, 111])
    @pytest.mark.parametrize('tcp', [None, 222])
    @pytest.mark.parametrize('ssl', [None, 333])
    @pytest.mark.parametrize('ws_wss_transports', [
        (None, None, None),
        (444, None, ('ssl', 'tcp', 'wss', 'ws')),
        (None, 555, ('ssl', 'tcp', 'wss', 'ws')),
    ])
    def testExplicitPorts(self, registry, ssl, tcp, prefix,
                          ws_wss_transports, monkeypatch):
        """
        Test the omero.ports.xxx and omero.client.icetransports
        configuration properties during the generation
        of the configuration files
        """

        # Skip the JVM settings calculation for this test
        ws, wss, transports = ws_wss_transports
        kwargs = {}
        if prefix:
            kwargs["prefix"] = prefix
        if registry:
            kwargs["registry"] = registry
        if tcp:
            kwargs["tcp"] = tcp
        if ssl:
            kwargs["ssl"] = ssl
        if ws:
            kwargs["ws"] = ws
        if wss:
            kwargs["wss"] = wss
        for (k, v) in kwargs.iteritems():
            self.cli.invoke(
                ["config", "set", "omero.ports.%s" % k, "%s" % v],
                strict=True)

        if transports:
            self.cli.invoke(
                ["config", "set", "omero.client.icetransports", "%s" %
                 ','.join(transports)], strict=True)
            kwargs["transports"] = transports

        self.cli.invoke(self.args, strict=True)

        check_ice_config(self.cli.dir, **kwargs)
        check_registry(self.cli.dir, **kwargs)

    def testGlacier2Icessl(self, monkeypatch):
        """
        Test the omero.glacier2.IceSSL.* properties during the generation
        of the configuration files
        """

        # Skip the JVM settings calculation for this test
        # monkeypatch.setattr(omero.install.jvmcfg, "adjust_settings",
        #                     lambda x, y: {})

        if sys.platform == "darwin":
            expected_ciphers = '(AES)'
        else:
            expected_ciphers = 'ADH:!LOW:!MD5:!EXP:!3DES:@STRENGTH'
        glacier2 = [
            ("IceSSL.Ciphers", expected_ciphers),
            ("IceSSL.TestKey", "TestValue"),
        ]
        self.cli.invoke([
            "config", "set",
            "omero.glacier2." + glacier2[1][0], glacier2[1][1]],
            strict=True)
        self.cli.invoke(self.args, strict=True)
        check_templates_xml(self.cli.dir, glacier2)
