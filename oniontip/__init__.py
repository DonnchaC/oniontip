from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config.from_object('oniontip.config')
app.config.from_envvar('ONIONTIP_SETTINGS', silent=True)

db = SQLAlchemy(app)

if not app.debug:
    import logging
    from handlers import TlsSMTPHandler
    credentials = None
    if app.config['MAIL_USERNAME'] or app.config['MAIL_PASSWORD']:
        credentials = (app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
    mail_handler = TlsSMTPHandler(
        (app.config['MAIL_SERVER'], app.config['MAIL_PORT']),
        'no-reply@' + app.config['MAIL_SERVER'],app.config['ADMINS'],
        'OnionTip Failure', credentials
    )
    mail_handler.setLevel(logging.ERROR)
    app.logger.addHandler(mail_handler)

    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler('oniontip.log', 'a', 1 * 1024 * 1024, 10)
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    app.logger.setLevel(logging.INFO)
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.info('Oniontip startup')

import models
import views
import util