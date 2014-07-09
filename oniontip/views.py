from flask import request, jsonify, render_template, Response, send_file
from flask.ext.sqlalchemy import SQLAlchemy

from oniontip import app, db
from models import ForwardAddress
import util

import os
import sys
import re
import json
import qrcode
import StringIO
import math
import bitcoin # pybitcointools
import datetime

TX_FEE_PER_KB = 10000   # 
MIN_OUTPUT = 5460       # Bitcoin dust limit

@app.route('/')
def index():
    return app.open_resource("templates/index.html").read().replace('<!--%script_root%-->',request.script_root)

@app.route('/result.json', methods=['GET'])
def json_result():
    options = util.Opt(dict(request.args.items()))
    relays = util.determine_relays(options)
    return Response(json.dumps(relays, cls=util.ResultEncoder), mimetype='application/json')

@app.route('/payment.json', methods=['GET'])
def payment_info():
    """
    Retrieve and store the selected router's bitcoin address with a new bitcoin keypair
    """
    outputs = {}
    options = util.Opt(dict(request.args.items()))
    relays = util.determine_relays(options)

    for relay in relays['results']:
        # If this address already has an output, add the share
        if relay.bitcoin_address in outputs:
            outputs[relay.bitcoin_address] += relay.donation_share
        else:
            outputs[relay.bitcoin_address] = relay.donation_share
            
    if outputs:
        '''
        Retrieve last id and provide it when creating next privkey from seed.
        NOTE: Possible race condition? Two people may get the same address?
        '''
        last_address = ForwardAddress.query.order_by(ForwardAddress.id.desc()).first()
        previous_id = last_address.id if last_address else 0

        donation_request = ForwardAddress(outputs=outputs, previous_n=previous_id)
        db.session.add(donation_request)
        db.session.commit()
        return Response(json.dumps({
                'status': 'success',
                'data': {
                    'message': 'A new bitcoin address forwarding to the {} selected relays has been created'.format(len(outputs)), 
                    'bitcoin_address': donation_request.address
            }}), mimetype='application/json'), 201

    else:
        return Response(json.dumps({'status': 'We could not find any relays which meet your criteria'}), mimetype='application/json'), 400

@app.route('/qr/<address>')
def get_qrcode(address):
    """Generate a QR Code"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=6,
        border=2,
    )

    qr.add_data('bitcoin:'+str(address))
    qr.make(fit=True)

    img = qr.make_image()

    img_io = StringIO.StringIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

def check_and_send(address):
    '''
    Check generated addresses and forwarded any unspent outputs

    Check_and_send does the heavy lifting for creating the bitcoin transactions for
    users on the web interface and for requests from the automated cronjob on the CLI
    '''
    try:
        address_history = bitcoin.history(address)
    except Exception, err:
        return {'status': 'error',
                'message': '<strong>Blockchain.info Error:</strong> {}'.format(str(err))
                }

    address_unspent = [output for output in address_history if not 'spend' in output]

    if address_history and not address_unspent:
        return {'status': 'fail',
                'data': { 
                    'message': 'There are no bitcoins remaining at this address. Have they been forwarded already? <a target="_blank" href="https://blockchain.info/address/'+address+'">'+address[0:10]+'..</a>',
                    'code': 404
                }}

    elif not address_unspent:
        return {'status': 'fail',
                'data': {
                    'message': 'No transaction has been received yet.',
                    'code': 404
                }}

    address_info = ForwardAddress.query.filter_by(address=address).first()
    if address_info:
        estimate_fee = util.calculate_fee(num_inputs=len(address_unspent),num_outputs=len(address_info.outputs), kb_tx_fee=TX_FEE_PER_KB)
        unspent_value = sum(output.get('value') for output in address_unspent)
        spendable_value = unspent_value - estimate_fee 
        if spendable_value <= 0:
            return {'status': 'fail',
                    'data': {
                        'message': 'There is not enough unspent bitcoin at this address to pay the transaction fee of {estimate_fee} satoshis.'.format(),
                        'code': 500
                    }}
        
        outs = []
        discarded_value = 0
        # Create the outputs, if any are too small, remove them and add them to remaining as can only get bigger
        for address, donation_percent in address_info.outputs.iteritems():
            value = int(math.floor((donation_percent * 0.01) * spendable_value))
            if value >= MIN_OUTPUT:
                outs.append({
                    'address': address,
                    'value': value
                })
            else:
                discarded_value += value
        if discarded_value > 0:
            for out in outs:
                new_ratio = float(out['value']) / (spendable_value - discarded_value)
                out['value'] += int(math.floor(new_ratio * discarded_value))

        if not outs:
            return {'status': 'fail',
                    'data': {
                        'message': 'There are no addresses to which the donation can be forwarded to successfully.',
                        'code': 500
                    }}

        raw_tx = bitcoin.transaction.mktx(address_unspent, outs)
        tx = bitcoin.transaction.signall(raw_tx, address_info.private_key)
        tx_hash = bitcoin.transaction.txhash(tx)

        try:
            push_result = bitcoin.pushtx(tx)

            # This address has been successfully spent from and doesn't need to be checked again.
            address_info.spent = True
            db.session.commit()

            return {'status': 'success',
                    'data': {
                        'message': '<strong>Success!</strong> Your transaction was received and forwarded to your selected relays. '
                                    '<a target="_blank" href="https://blockchain.info/tx/'+tx_hash+'">'+tx_hash[0:10]+'..</a>',
                        'tx_hash': tx_hash
                    }}
        except Exception, err:
            if err:
                return {'status': 'error',
                        'message': '<strong>Blockchain.info Error:</strong> {}.'.format(err)
                        }
            else:
                return {'status': 'error',
                        'message': 'There was an unknown error when trying to push the forwarding transaction to the blockchain.'
                        }

    else:
        return {'status': 'fail',
                'data': {
                    'message': 'Could not find the keys for this address in the database.',
                    'code': 404
                    }}

def find_unsent_payments():
    """
    Forward unspent transactions sent to oniontip addresses

    This function is called from the CLI to recheck recent
    addresses (< 2 hours) for any payments which the user
    may not have forwarded on the web UI. 
    """

    unspent_addresses = ForwardAddress.query.filter_by(spent=False, expired=False).all()
    successful_txs = []
    for unspent in unspent_addresses:
        if (datetime.datetime.utcnow() - unspent.created) < datetime.timedelta(hours=2):
            response = check_and_send(unspent.address)
            if response.get('status') == 'success':
                successful_txs.append({
                    'address': unspent.address,
                    'tx_hash': response['data']['tx_hash']}
                    )
            elif response.get('status') == 'fail':
                print response['data']['message']
            elif response.get('status') == 'error':
                print response['message']
            else:
                print 'An unknown error occured in the application.'
        else:
            # These addresses are older than two hours and should be marked expired
            unspent.expired = True
            db.session.commit()

    return successful_txs

@app.route('/forward/<address>')
def forward_from_address(address):
    '''
    Parse the results of the check_and_send function and provide the
    correct HTTP response codes for display to the user on the frontend.
    '''
    response = check_and_send(address)
    if response.get('status') == 'success':
        return Response(json.dumps(response), mimetype='application/json')
    elif response.get('status') == 'fail' or response.get('status') == 'error':
        return Response(json.dumps(response), mimetype='application/json'), response['data'].get('code', 500)
    else:
        return Response(json.dumps({'message': 'An unknown error occured in the application.'}), mimetype='application/json'), 500