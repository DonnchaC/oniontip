from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config.from_object('oniontip.config')
app.config.from_envvar('ONIONTIP_SETTINGS', silent=True)

db = SQLAlchemy(app)

import models
import views
import util