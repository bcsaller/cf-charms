#!/usr/bin/env python
# vim: et sta sts ai ts=4 sw=4:

import os
import sys
import time
import subprocess
from cloudfoundry import ROUTER_PACKAGES
from charmhelpers.core import hookenv, host
from charmhelpers.payload.execd import execd_preinstall

config_data = hookenv.config()
#CC_PORT =
#CF_USER =
#ROUTER_PORT =

from charmhelpers.core.hookenv import \
    (
        CRITICAL, ERROR, WARNING, INFO, DEBUG,
    )

from charmhelpers.fetch import (
    apt_install,
    apt_update,
    filter_installed_packages,
    add_source
)


def Template(*args, **kw):
    """jinja2.Template with deferred jinja2 import.

    jinja2 may not be importable until the install hook has installed the
    required packages.
    """
    from jinja2 import Template
    return Template(*args, **kw)

hooks = hookenv.Hooks()


def log(msg, lvl=INFO):
    myname = hookenv.local_unit().replace('/', '-')
    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    with open('{}/{}-debug.log'.format(juju_log_dir, myname), 'a') as f:
        f.write('{} {}: {}\n'.format(ts, lvl, msg))
    hookenv.log(msg, lvl)


def run(command, exit_on_error=True, quiet=False):
    '''Run a command and return the output.'''
    if not quiet:
        log("Running {!r}".format(command), DEBUG)
    p = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        shell=isinstance(command, basestring))
    p.stdin.close()
    lines = []
    for line in p.stdout:
        if line:
            # LP:1274460 & LP:1259490 mean juju-log is no where near as
            # useful as we would like, so just shove a copy of the
            # output to stdout for logging.
            # log("> {}".format(line), DEBUG)
            if not quiet:
                print line
            lines.append(line)
        elif p.poll() is not None:
            break

    p.wait()

    if p.returncode == 0:
        return '\n'.join(lines)

    if p.returncode != 0 and exit_on_error:
        log("ERROR: {}".format(p.returncode), ERROR)
        sys.exit(p.returncode)

    raise subprocess.CalledProcessError(
        p.returncode, command, '\n'.join(lines))


hooks = hookenv.Hooks()


@hooks.hook()
def install():
    execd_preinstall()
    print 'DEBUG', config_data['source']
    add_source(config_data['source'], config_data['key'])
    apt_update(fatal=True)
    apt_install(packages=ROUTER_PACKAGES, fatal=True)
    #install_upstart_scripts()
#    run(['apt-key', 'adv', '--keyserver', 'keyserver.ubuntu.com', '--recv-keys', '4C430C3C2828E07D'])
#    run(['add-apt-repository', 'ppa:cf-charm/ppa'])
#    run(['apt-get', 'update'])
    #TODO replace with real name of the package
#    run(['apt-get', 'install', '-y', 'cfgorouter', 'cfgorouterjob'])
    #host.adduser(CF_USER)


@hooks.hook()
def start():
    log("Begin start hook")
    log("Starting router daemonized in the background")
    #host.service_start('cf-router')
    #hookenv.open_port(ROUTER_PORT)


@hooks.hook("config-changed")
def config_changed():
    pass
    #hookenv.close_port(ROUTER_PORT)
    #hookenv.open_port(ROUTER_PORT)


@hooks.hook()
def stop():
    pass
    #host.service_stop('cf-router')
    #hookenv.close_port(ROUTER_PORT)


@hooks.hook('db-relation-changed')
def cc_relation_changed():
    pass


hook_name = os.path.basename(sys.argv[0])
juju_log_dir = "/var/log/juju"

if __name__ == '__main__':
    # Hook and context overview. The various replication and client
    # hooks interact in complex ways.
    log("Running {} hook".format(hook_name))
    if hookenv.relation_id():
        log("Relation {} with {}".format(
            hookenv.relation_id(), hookenv.remote_unit()))
    hooks.execute(sys.argv)
