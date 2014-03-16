#!/usr/bin/env python
# vim: et ai ts=4 sw=4:

import os
import sys
import time
import subprocess
import glob
import shutil
import pwd
import grp
import cPickle as pickle

from charmhelpers.core import hookenv, host
from charmhelpers.payload.execd import execd_preinstall

from charmhelpers.core.hookenv import log
from charmhelpers.fetch import (
    apt_install, apt_update, add_source
)
from utils import render_template
hooks = hookenv.Hooks()

CC_PACKAGES = ['cfcloudcontroller', 'cfcloudcontrollerjob']

CF_DIR = '/var/lib/cloudfoundry'
CC_DIR = '{}/cfcloudcontroller'.format(CF_DIR)
CC_CONFIG_DIR = '{}/jobs/config'.format(CC_DIR)
CC_CONFIG_FILE = '{}/cloud_controller_ng.yml'.format(CC_CONFIG_DIR)
CC_DB_FILE = '{}/db/cc.db'.format(CC_DIR)
CC_JOB_FILE = '/etc/init/cf-cloudcontroller.conf'
CC_LOG_DIR = '/var/vcap/sys/log/cloud_controller_ng'
CC_RUN_DIR = '/var/vcap/sys/run/cloud_controller_ng'

NGINX_JOB_FILE = '/etc/init/cf-nginx.conf'
NGINX_CONFIG_FILE = '{}/nginx.conf'.format(CC_CONFIG_DIR)
NGINX_RUN_DIR = '/var/vcap/sys/run/nginx_ccng'
NGINX_LOG_DIR = '/var/vcap/sys/log/nginx_ccng'

FOG_CONNECTION = '/var/vcap/nfs/store'


def chownr(path, owner, group):
    uid = pwd.getpwnam(owner).pw_uid
    gid = grp.getgrnam(group).gr_gid
    for root, dirs, files in os.walk(path):
        for momo in dirs:
            os.chown(os.path.join(root, momo), uid, gid)
            for momo in files:
                os.chown(os.path.join(root, momo), uid, gid)


def install_upstart_scripts():
    for x in glob.glob('files/upstart/*.conf'):
        log('Installing upstart job:' + x, DEBUG)
        shutil.copy(x, '/etc/init/')


def run(command, exit_on_error=True, quiet=False):
    '''Run a command and return the output.'''
    if not quiet:
        log("Running {!r}".format(command), hookenv.DEBUG)
    p = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        shell=isinstance(command, basestring))
    p.stdin.close()
    lines = []
    for line in p.stdout:
        if line:
            if not quiet:
                print line
            lines.append(line)
        elif p.poll() is not None:
            break

    p.wait()

    if p.returncode == 0:
        return '\n'.join(lines)

    if p.returncode != 0 and exit_on_error:
        log("ERROR: {}".format(p.returncode), hookenv.ERROR)
        sys.exit(p.returncode)

    raise subprocess.CalledProcessError(
        p.returncode, command, '\n'.join(lines))


hooks = hookenv.Hooks()


class State(dict):
    """Encapsulate state common to the unit for republishing to relations."""
    def __init__(self, state_file):
        super(State, self).__init__()
        self._state_file = state_file
        self.load()

    def load(self):
        '''Load stored state from local disk.'''
        if os.path.exists(self._state_file):
            state = pickle.load(open(self._state_file, 'rb'))
        else:
            state = {}
        self.clear()

        self.update(state)

    def save(self):
        '''Store state to local disk.'''
        state = {}
        state.update(self)
        pickle.dump(state, open(self._state_file, 'wb'))


#TODO move to class
def alter_state_value(name, value):
    log('State\'s value altered:' + name + '->' + str(value))
    if name in local_state:
        local_state[name] = value
    else:
        local_state.setdefault(name, value)
    local_state.save()


def set_cc_conf_state(state):
    alter_state_value('cc_conf', state)


def emit_cc_conf():
    cc_context = {}
    cc_context.setdefault('domain', config_data['domain'])
    if 'nats_user' in local_state:
        cc_context.setdefault('nats_user', local_state['nats_user'])
    else:
        return False
    if 'nats_password' in local_state:
        cc_context.setdefault('nats_password', local_state['nats_password'])
    else:
        return False
    cc_context.setdefault('system_domain_organization',
                          config_data['system_domain_organization'])
    cc_context.setdefault('cc_ip', hookenv.unit_private_ip())
    if config_data['external_domain']:
        cc_context.setdefault('external_domain',
                              config_data['external_domain'])
    else:
        cc_context.setdefault('external_domain', 'localhost')
    if config_data['system_domain']:
        cc_context.setdefault('system_domain',
                              config_data['system_domain'])
    else:
        log('No system_domain')
        return False
    if config_data['cc_port']:
        cc_context.setdefault('cc_port', config_data['cc_port'])
    else:
        set_cc_conf_state('')
        return False
    if 'nats_port' in local_state:
        cc_context.setdefault('nats_port', local_state['nats_port'])
    else:
        set_cc_conf_state('')
        return False
    if 'nats_address' in local_state:
        cc_context.setdefault('nats_address', local_state['nats_address'])
    else:
        set_cc_conf_state('')
        return False
    os.chdir(hookenv.charm_dir())
    with open(CC_CONFIG_FILE, 'w') as cc_conf:
        cc_conf.write(render_template('cloud_controller_ng.yml', cc_context))
    set_cc_conf_state('ok')
    return True


def emit_nginx_conf():
    nginx_context = {
        'nginx_port': config_data['nginx_port'],
    }
    os.chdir(hookenv.charm_dir())
    with open(NGINX_CONFIG_FILE, 'w') as nginx_conf:
        nginx_conf.write(render_template('nginx.conf', nginx_context))


def port_config_changed(port):
    '''Cheks if value of port changed close old port and open a new one'''
    if port in local_state:
        if local_state[port] != config_data[port]:
            hookenv.close_port(local_state[port])
            local_state[port] = config_data[port]
    else:
        local_state.setdefault(port, config_data[port])
    local_state.save()
    hookenv.open_port(config_data[port])


def cc_db_migrate():
    log("Starting db:migrate...")
    os.chdir(CC_DIR)
    run(['sudo', '-u', 'vcap', '-g', 'vcap',
        'CLOUD_CONTROLLER_NG_CONFIG={}'.format(CC_CONFIG_FILE),
        'bundle', 'exec', 'rake', 'db:migrate'])
    alter_state_value('ccdbmigrated', 'true')


@hooks.hook()
def install():
    execd_preinstall()
    add_source(config_data['source'], config_data['key'])
    apt_update(fatal=True)
    apt_install(packages=CC_PACKAGES, fatal=True)
    host.adduser('vcap')
    host.write_file(CC_DB_FILE, '', owner='vcap', group='vcap', perms=0775)
    dirs = [CC_RUN_DIR, NGINX_RUN_DIR, CC_LOG_DIR, NGINX_LOG_DIR,
            '/var/vcap/data/cloud_controller_ng/tmp/uploads',
            '/var/vcap/data/cloud_controller_ng/tmp/staged_droplet_uploads',
            '/var/vcap/nfs/store']
    for item in dirs:
        host.mkdir(item, owner='vcap', group='vcap', perms=0775)
    chownr('/var/vcap', owner='vcap', group='vcap')
    chownr(CF_DIR, owner='vcap', group='vcap')
    install_upstart_scripts()
    run(['update-rc.d', '-f', 'nginx', 'remove'])
    #reconfigure NGINX as upstart job and use specific config file
    host.service_stop('nginx')
    os.remove('/etc/init.d/nginx')


@hooks.hook("config-changed")
def config_changed():
    port_config_changed('nginx_port')
    emit_nginx_conf()
    if host.service_running('cf-nginx'):
        #TODO replace with config reload
        host.service_restart('cf-nginx')
        if host.service_running('cf-cloudcontroller') and emit_cc_conf():
            host.service_restart('cf-cloudcontroller')


@hooks.hook()
def start():
    if ('cc_conf' in local_state) and ('ccdbmigrated' in local_state):
        if not host.service_running('cf-cloudcontroller'):
            log("Starting cloud controller as upstart job")
            host.service_start('cf-cloudcontroller')
        if (not host.service_running('cf-nginx')) and \
                host.service_running('cf-cloudcontroller'):
            log("Starting NGINX")
            host.service_start('cf-nginx')
    hookenv.open_port(local_state['nginx_port'])


@hooks.hook()
def stop():
    if host.service_running('cf-nginx'):
        host.service_stop('cf-nginx')
    if host.service_running('cf-cloudcontroller'):
        host.service_stop('cf-cloudcontroller')
    hookenv.close_port(local_state['nginx_port'])


@hooks.hook('db-relation-changed')
def db_relation_changed():
    pass


@hooks.hook('nats-relation-changed')
def nats_relation_changed():
    for relid in hookenv.relation_ids('nats'):
        alter_state_value('nats_address', hookenv.relation_get('nats_address'))
        alter_state_value('nats_port', hookenv.relation_get('nats_port'))
        alter_state_value('nats_user', hookenv.relation_get('nats_user'))
        alter_state_value('nats_password',
                          hookenv.relation_get('nats_password'))
    if emit_cc_conf():
        if not 'ccdbmigrated' in local_state:
            cc_db_migrate()
        start()


@hooks.hook('nats-relation-broken')
def nats_relation_broken():
    stop()


@hooks.hook('nats-relation-departed')
def nats_relation_departed():
    pass

config_data = hookenv.config()
hook_name = os.path.basename(sys.argv[0])
local_state = State('local_state.pickle')

if __name__ == '__main__':
    # Hook and context overview. The various replication and client
    # hooks interact in complex ways.
    log("Running {} hook".format(hook_name))
    if hookenv.relation_id():
        log("Relation {} with {}".format(
            hookenv.relation_id(), hookenv.remote_unit()))
    hooks.execute(sys.argv)
