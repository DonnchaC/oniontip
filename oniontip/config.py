# -*- config:utf-8 -*-
import os

project_name = 'oniontip'
basedir = os.path.abspath(os.path.dirname(__file__))

DEBUG = False
TESTING = False

# DATABASE CONFIGURATION
SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'sqlite.db')
LOGGER_NAME = "%s_log" % project_name

# BITCOIN ADDRESS SEED - MUST BE SET TO A RANDOM VALUE
BITCOIN_KEY_SEED = os.environ.get('BITCOIN_KEY_SEED')