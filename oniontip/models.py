from oniontip import db
from flask import current_app
import bitcoin
import datetime

class ForwardAddress(db.Model):
    __table_args__ = {'sqlite_autoincrement': True} # Make sure id's aren't reused

    id = db.Column(db.Integer, primary_key=True)
    private_key = db.Column(db.String(80), unique=True)
    public_key = db.Column(db.String(80), unique=True)
    address = db.Column(db.String(80), unique=True)
    outputs = db.Column(db.PickleType, nullable=False)
    created = db.Column(db.DateTime)
    spent = db.Column(db.Boolean, default=False)
    expired = db.Column(db.Boolean, default=False)

    def __init__(self, private_key=None, outputs=None, previous_n=0):
        if not private_key:
            self.private_key = bitcoin.electrum_privkey(current_app.config.get('BITCOIN_KEY_SEED'), previous_n+1)
        else:
            self.private_key = private_key
        self.public_key = bitcoin.privtopub(self.private_key)
        self.address = bitcoin.pubtoaddr(self.public_key)
        self.outputs = outputs
        self.created = datetime.datetime.utcnow()

    def __unicode__(self):
        return self.address

class DataStore(db.Model):
    """Simple Key/value data store instead of using flat file"""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True)
    value = db.Column(db.String(300))

    def __init__(self, key=None, value=None):
        self.key = key
        self.value = value

    def __unicode__(self):
        return (self.key, self.value)