#!/usr/bin/env python
# vim: et ai ts=4 sw=4:

import os

import sys
# import glob
import shutil

from helpers.config_helper import find_config_parameter, emit_config
from helpers.upstart_helper import install_upstart_scripts
from helpers.common import chownr, run
from helpers.state import State

from charmhelpers.core import hookenv, host
# from charmhelpers.core.hookenv import log, DEBUG, ERROR, WARNING
from charmhelpers.core.hookenv import log, DEBUG

from charmhelpers.fetch import (
    apt_install, apt_update, add_source, filter_installed_packages
)
# from utils import render_template

hooks = hookenv.Hooks()


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


def all_configs_are_rendered():
    return local_state['varz_ok'] and \
        local_state['registrar_ok'] and \
        local_state['uaa_ok']


def emit_all_configs():
    emit_registrar_config()
    emit_varz_config()
    emit_uaa_config()


def emit_registrar_config():
    required_config_items = ['nats_user', 'nats_password', 'nats_address',
                             'nats_port', 'varz_user', 'varz_password',
                             'uaa_ip', 'domain']

    emit_config('registrar', required_config_items, local_state,
                'registrar.yml', REGISTRAR_CONFIG_FILE)


def emit_varz_config():
    required_config_items = ['varz_password', 'varz_user']
    emit_config('varz', required_config_items, local_state,
                'varz.yml', VARZ_CONFIG_FILE)


def emit_uaa_config():
    required_config_items = []
    emit_config('uaa', required_config_items, local_state,
                'uaa.yml', UAA_CONFIG_FILE)


@hooks.hook()
def install():
    add_source(config_data['source'], config_data['key'])
    apt_update(fatal=True)
    log("Installing required packages", DEBUG)
    apt_install(packages=filter_installed_packages(PACKAGES), fatal=True)
    host.adduser('vcap')
    install_upstart_scripts()
    if os.path.isfile('/etc/init.d/tomcat7'):
        run(['update-rc.d', '-f', 'tomcat7', 'remove'])
        log("Stopping Tomcat ...", DEBUG)
        host.service_stop('tomcat7')
        os.remove('/etc/init.d/tomcat7')
    dirs = [RUN_DIR, LOG_DIR, '/var/vcap/jobs/uaa']
    for item in dirs:
        host.mkdir(item, owner='vcap', group='vcap', perms=0775)
    if not os.path.isfile(os.path.join(TOMCAT_HOME,
                          'lib', 'sqlite-jdbc-3.7.2.jar')):
        os.chdir(os.path.join(TOMCAT_HOME, 'lib'))
        log('Installing SQLite jdbc driver jar into Tomcat lib directory',
            DEBUG)
        # TODO consider installing from charm
        run(['wget', 'https://bitbucket.org/xerial/sqlite-jdbc/downloads/'
            'sqlite-jdbc-3.7.2.jar'])
    log("Cleaning up old config files", DEBUG)
    shutil.rmtree(CONFIG_PATH)
    shutil.copytree(os.path.join(hookenv.charm_dir(),
                    'files/config'), CONFIG_PATH)
    host.mkdir('var/vcap/jobs/uaa', owner='vcap', group='vcap', perms=0775)
    os.chdir('var/vcap/jobs/uaa')
    os.symlink('/var/lib/cloudfoundry/cfuaa/jobs/config',
               'config')
    chownr('/var/vcap', owner='vcap', group='vcap')
    chownr(CF_DIR, owner='vcap', group='vcap')


@hooks.hook("config-changed")
def config_changed():
    local_state['varz_ok'] = False
    local_state['registrar_ok'] = False
    local_state['uaa_ok'] = False

    config_items = ['nats_user', 'nats_password', 'nats_port',
                    'nats_address', 'varz_user', 'varz_password',
                    'uaa_ip', 'domain']

    for key in config_items:
        value = find_config_parameter(key, hookenv, config_data)
        log(("%s = %s" % (key, value)), DEBUG)
        local_state[key] = value

    local_state['uaa_ip'] = hookenv.unit_private_ip()

    local_state.save()

    emit_all_configs()

    stop()
    start()
    # TODO replace with config reload
    # host.service_restart('cf-uaa')
    # host.service_restart('cf-registrar')


@hooks.hook()
def start():
    log("UAA: Start hook is called.")
    if all_configs_are_rendered():
        log("UAA: Start hook: all configs are rendered.")
        if not host.service_running('cf-uaa'):
            log("Starting UAA as upstart job")
            host.service_start('cf-uaa')
        if not host.service_running('cf-registrar'):
            log("Starting cf registrar as upstart job")
            host.service_start('cf-registrar')
    else:
        log("UAA: Start hook: NOT all configs are rendered.")


@hooks.hook()
def stop():
    if host.service_running('cf-uaa'):
        host.service_stop('cf-uaa')
    if host.service_running('cf-registrar'):
        host.service_stop('cf-registrar')
    #     hookenv.close_port(local_state['uaa_port'])


@hooks.hook('nats-relation-changed')
def nats_relation_changed():
    log("UAA: nats-relation-changed >>> (attempt to add NATS) ")
    config_changed()


@hooks.hook('nats-relation-broken')
def nats_relation_broken():
    # TODO: determine how to notify user and what to do
    log("UAA: nats_relation_broken.")
    config_changed()    # will only stop if someone will be missing


@hooks.hook('uaa-relation-joined')
def uaa_relation_joined():
    log('UAA: uaa-relation-joined', DEBUG)
    # for relid in hookenv.relation_ids('uaa'):


#################### Global variables ####################
PACKAGES = ['cfuaa', 'cfuaajob', 'cfregistrar']
CF_DIR = '/var/lib/cloudfoundry'
RUN_DIR = '/var/vcap/sys/run/uaa'
LOG_DIR = '/var/vcap/sys/log/uaa'
CONFIG_PATH = os.path.join(CF_DIR, 'cfuaa', 'jobs', 'config')
UAA_CONFIG_FILE = os.path.join(CONFIG_PATH, 'uaa.yml')
VARZ_CONFIG_FILE = os.path.join(CONFIG_PATH, 'varz.yml')
REGISTRAR_CONFIG_FILE = os.path.join(CF_DIR, 'cfregistrar',
                                             'config', 'config.yml')
TOMCAT_HOME = '/var/lib/cloudfoundry/cfuaa/tomcat'
SQLITE_JDBC_LIBRARY = 'sqlite-jdbc-3.7.2.jar'
config_data = hookenv.config()
hook_name = os.path.basename(sys.argv[0])
local_state = State('local_state.pickle')
#################### Global variables ####################


if __name__ == '__main__':
    # Hook and context overview. The various replication and client
    # hooks interact in complex ways.
    log("Running {} hook".format(hook_name))
    if hookenv.relation_id():
        log("Relation {} with {}".format(
            hookenv.relation_id(), hookenv.remote_unit()))
    hooks.execute(sys.argv)
